"""Bulk-ingest fundamentals for a list of tickers.

The pipeline is straightforward:

1. For each ticker, optionally check the DB for a fresh-enough snapshot
   (configurable via ``stale_after_days``) and skip if already cached.
2. Call ``provider.metadata(ticker)`` for proper company name / sector.
3. Call ``provider.fetch(ticker)`` for the current snapshot.
4. Optionally call ``provider.history(ticker)`` for annual/quarterly history.
5. Persist instrument + snapshot(s) to ``instruments`` + ``fundamentals_snapshots``.
6. Sleep ``rate_limit_seconds`` between tickers to be a polite client.

Failures don't take down the whole run — bad tickers are collected in
``IngestSummary.failed`` and reported at the end.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openbourse.db.models import FundamentalsRow, InstrumentRow
from openbourse.db.repositories import (
    FundamentalsRepository,
    InstrumentRepository,
    SyncRunRepository,
)
from openbourse.domain import FundamentalsSnapshot, Instrument
from openbourse.providers.base import Providers
from openbourse.universe.sources import fetch_source

# Index sources synced by default — the major US benchmarks most screens
# filter against. Override via the ``sources`` argument to add Russell, etc.
DEFAULT_SYNC_SOURCES: tuple[str, ...] = ("sp500", "nasdaq100", "dow30")


@dataclass
class IngestSummary:
    """Aggregate result of a bulk ingest run."""

    total: int = 0
    ingested: int = 0
    skipped_fresh: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Fraction of attempted tickers that ingested cleanly (0.0 to 1.0)."""
        return (self.ingested / self.total) if self.total else 0.0


ProgressFn = Callable[[str, int, int], None]


async def ingest_tickers(
    tickers: Sequence[str],
    providers: Providers,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    with_history: bool = False,
    rate_limit_seconds: float = 0.2,
    stale_after_days: int = 0,
    progress: ProgressFn | None = None,
) -> IngestSummary:
    """Bulk-ingest fundamentals for ``tickers`` via the configured provider.

    Each ticker uses its own short-lived session so a single failure can't
    block the rest. ``progress(ticker, index, total)`` is called before each
    fetch, suitable for driving a Rich progress bar in a CLI.
    """
    summary = IngestSummary(total=len(tickers))
    for index, ticker in enumerate(tickers):
        ticker = ticker.upper()
        if progress is not None:
            progress(ticker, index, len(tickers))

        try:
            async with session_factory() as session:
                if stale_after_days > 0 and await _is_fresh(session, ticker, stale_after_days):
                    summary.skipped_fresh += 1
                    continue
                await _ingest_one(session, providers, ticker, with_history=with_history)
            summary.ingested += 1
        except KeyError as exc:
            summary.failed.append((ticker, str(exc)))
        except Exception as exc:  # network / db / provider quirks
            summary.failed.append((ticker, f"{type(exc).__name__}: {exc}"))

        # Polite pause — prevents Yahoo's "Too Many Requests" throttle and
        # gives FMP free-tier headroom even at large list sizes.
        if rate_limit_seconds > 0:
            await asyncio.sleep(rate_limit_seconds)

    return summary


@dataclass
class SyncResult:
    """Aggregate result of a :func:`force_sync_universe` run.

    ``sources`` maps each successfully-fetched source name to its constituent
    count. ``source_errors`` collects sources that failed to fetch (Wikipedia
    layout change, network blip) — those are skipped so the rest still sync.
    ``ingest`` is the underlying bulk-ingest summary for the deduped union.
    ``synced_at`` is the UTC time the run was recorded to the ``sync_runs``
    audit table — ``None`` when nothing ingested, so no sync was recorded.
    """

    sources: dict[str, int] = field(default_factory=dict)
    source_errors: list[tuple[str, str]] = field(default_factory=list)
    ingest: IngestSummary = field(default_factory=IngestSummary)
    synced_at: datetime | None = None

    @property
    def unique_tickers(self) -> int:
        """Number of distinct tickers across all fetched sources."""
        return self.ingest.total


async def force_sync_universe(
    providers: Providers,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    sources: Sequence[str] = DEFAULT_SYNC_SOURCES,
    with_history: bool = False,
    rate_limit_seconds: float = 0.2,
    progress: ProgressFn | None = None,
    source_fetcher: Callable[[str], list[str]] = fetch_source,
) -> SyncResult:
    """Fetch the latest constituents for ``sources`` and force-ingest them all.

    "Force" means ``stale_after_days=0`` — every ticker is re-fetched from the
    provider regardless of how recently it was last ingested, so screening
    filters always run against fully up-to-date fundamentals.

    Constituents from all sources are unioned and de-duplicated (a ticker in
    both the S&P 500 and Nasdaq-100 is fetched once). A source that fails to
    fetch is recorded in :attr:`SyncResult.source_errors` and skipped; the
    remaining sources still sync.

    ``source_fetcher`` is injectable purely for testing — production callers
    use the default :func:`openbourse.universe.sources.fetch_source`.
    """
    result = SyncResult()
    seen: set[str] = set()
    combined: list[str] = []
    for name in sources:
        try:
            tickers = source_fetcher(name)
        except Exception as exc:  # network / layout-change / unknown source
            result.source_errors.append((name, f"{type(exc).__name__}: {exc}"))
            continue
        result.sources[name] = len(tickers)
        for ticker in tickers:
            upper = ticker.upper()
            if upper not in seen:
                seen.add(upper)
                combined.append(upper)

    result.ingest = await ingest_tickers(
        combined,
        providers,
        session_factory,
        with_history=with_history,
        rate_limit_seconds=rate_limit_seconds,
        stale_after_days=0,  # force — never skip on freshness
        progress=progress,
    )

    # Record the sync only when data actually landed — a run that ingested
    # nothing (every source down) shouldn't reset "DB last synced".
    if result.ingest.ingested > 0:
        async with session_factory() as session:
            run = await SyncRunRepository(session).record(
                sources=list(result.sources),
                ticker_count=result.ingest.total,
                ingested=result.ingest.ingested,
                failed=len(result.ingest.failed),
            )
            await session.commit()
        result.synced_at = run.synced_at

    return result


async def _ingest_one(
    session: AsyncSession,
    providers: Providers,
    ticker: str,
    *,
    with_history: bool,
) -> None:
    """Fetch + persist one ticker. Raises KeyError on unknown / restricted."""
    instrument = await _resolve_instrument(providers, ticker)
    snapshot = await providers.fundamentals.fetch(ticker)

    instr_repo = InstrumentRepository(session)
    fund_repo = FundamentalsRepository(session)
    inst_row = await instr_repo.upsert(instrument)
    await session.flush()
    await fund_repo.upsert(inst_row.id, snapshot)

    if with_history:
        history = await providers.fundamentals.history(ticker)
        for hist_snap in history:
            await fund_repo.upsert(inst_row.id, hist_snap)

    await session.commit()


async def _resolve_instrument(providers: Providers, ticker: str) -> Instrument:
    """Pull metadata via the provider; fall back to a ticker-only stub on failure.

    A metadata lookup may legitimately fail (provider returns 402 / 404 for a
    name that fetch() will also fail on). Letting fetch() be the source of
    truth for "is this ticker valid" keeps error paths consistent.
    """
    try:
        return await providers.fundamentals.metadata(ticker)
    except (KeyError, AttributeError):
        return Instrument(ticker=ticker.upper(), name=ticker.upper())


async def _is_fresh(session: AsyncSession, ticker: str, stale_after_days: int) -> bool:
    """Return True when a snapshot for ``ticker`` is newer than ``stale_after_days``."""
    cutoff = datetime.now(UTC).date() - timedelta(days=stale_after_days)
    stmt = (
        select(FundamentalsRow.as_of)
        .join(InstrumentRow, InstrumentRow.id == FundamentalsRow.instrument_id)
        .where(InstrumentRow.ticker == ticker.upper())
        .order_by(FundamentalsRow.as_of.desc())
        .limit(1)
    )
    latest = await session.scalar(stmt)
    return latest is not None and latest >= cutoff


# Re-export for convenience.
__all__ = [
    "DEFAULT_SYNC_SOURCES",
    "IngestSummary",
    "ProgressFn",
    "SyncResult",
    "force_sync_universe",
    "ingest_tickers",
]


# Help mypy realise FundamentalsSnapshot is in scope; kept for documentation.
_ = FundamentalsSnapshot
