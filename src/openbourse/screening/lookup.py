"""Single-ticker lookup: fetch fundamentals, score, return a Candidate.

Used by both the ``bourse lookup`` CLI command and the TUI lookup modal so
the two paths produce identical results from the same inputs.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from openbourse.db.repositories import FundamentalsRepository, InstrumentRepository
from openbourse.domain import Candidate, FundamentalsSnapshot, Instrument
from openbourse.providers.base import Providers
from openbourse.screening.scoring import Weights, composite_score, verdict_for


class TickerLookupError(Exception):
    """Raised when a ticker cannot be resolved by the configured fundamentals provider."""


async def lookup_candidate(
    ticker: str,
    providers: Providers,
    *,
    session: AsyncSession | None = None,
    weights: Weights | None = None,
) -> Candidate:
    """Resolve ``ticker`` to a fully-scored :class:`Candidate`.

    The instrument metadata is looked up in the database when ``session`` is
    provided; otherwise a minimal :class:`Instrument` is synthesised from the
    ticker alone. Fundamentals always come from
    ``providers.fundamentals.fetch``.

    Raises :class:`TickerLookupError` if the provider cannot resolve the
    ticker (e.g. unknown symbol, network failure).
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise TickerLookupError("ticker is required")

    instrument: Instrument | None = None
    if session is not None:
        instrument = await InstrumentRepository(session).get_by_ticker(ticker)
    if instrument is None:
        instrument = Instrument(ticker=ticker, name=ticker)

    try:
        snapshot = await providers.fundamentals.fetch(ticker)
    except KeyError as exc:
        raise TickerLookupError(f"unknown ticker: {ticker}") from exc

    score = composite_score(snapshot, weights=weights or Weights())
    return Candidate(
        instrument=instrument,
        snapshot=snapshot,
        score=score,
        verdict=verdict_for(score),
    )


async def lookup_with_history(
    ticker: str,
    providers: Providers,
    *,
    session: AsyncSession | None = None,
    weights: Weights | None = None,
    limit: int | None = None,
) -> tuple[Candidate, list[FundamentalsSnapshot]]:
    """Resolve ``ticker`` AND fetch its historical snapshots.

    When ``limit`` is omitted the provider's own default is used. This
    matters on the FMP free tier, where the provider tunes its default to
    fit the per-call row cap; passing a larger ``limit`` here would request
    more rows than the tier allows and the provider would 402.

    When ``session`` is provided, the freshly-fetched history (and the
    instrument metadata) is persisted via ``InstrumentRepository`` and
    ``FundamentalsRepository``. This means a CLI lookup followed by a TUI
    launch finds the new history in the startup query.

    Errors from the history call (network, missing endpoint, plan-tier
    restrictions) are swallowed and surfaced as an empty list — the
    candidate itself is unaffected.
    """
    candidate = await lookup_candidate(ticker, providers, session=session, weights=weights)

    history: list[FundamentalsSnapshot] = []
    try:
        if limit is None:
            history = await providers.fundamentals.history(ticker)
        else:
            history = await providers.fundamentals.history(ticker, limit=limit)
    except (KeyError, OSError, ValueError):
        history = []

    if session is not None and history:
        instr_repo = InstrumentRepository(session)
        fund_repo = FundamentalsRepository(session)
        inst_row = await instr_repo.upsert(candidate.instrument)
        await session.flush()
        for snap in history:
            await fund_repo.upsert(inst_row.id, snap)
        await session.commit()

    return candidate, history
