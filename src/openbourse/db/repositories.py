"""Repository layer translating between ORM rows and domain dataclasses."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from openbourse.db.models import FundamentalsRow, InstrumentRow, WatchlistRow
from openbourse.domain import FundamentalsSnapshot, Instrument


def _to_instrument(row: InstrumentRow) -> Instrument:
    return Instrument(
        ticker=row.ticker,
        name=row.name,
        sector=row.sector,
        exchange=row.exchange,
        cik=row.cik,
        business_summary=row.business_summary,
    )


def _to_snapshot(row: FundamentalsRow, ticker: str) -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        ticker=ticker,
        as_of=row.as_of,
        market_cap_usd=row.market_cap_usd,
        revenue_growth_pct=row.revenue_growth_pct,
        gross_margin_pct=row.gross_margin_pct,
        net_debt_to_ebitda=row.net_debt_to_ebitda,
        fcf_yield_pct=row.fcf_yield_pct,
        price_usd=row.price_usd,
        revenue_ttm_usd=row.revenue_ttm_usd,
        ebitda_ttm_usd=row.ebitda_ttm_usd,
    )


class InstrumentRepository:
    """CRUD over the ``instruments`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, instrument: Instrument) -> InstrumentRow:
        """Insert ``instrument`` or update the existing row sharing its ticker.

        Returns the persisted ORM row so callers can read its newly assigned
        primary key.
        """
        existing = await self.session.scalar(
            select(InstrumentRow).where(InstrumentRow.ticker == instrument.ticker)
        )
        if existing is None:
            existing = InstrumentRow(
                ticker=instrument.ticker,
                name=instrument.name,
                sector=instrument.sector,
                exchange=instrument.exchange,
                cik=instrument.cik,
                business_summary=instrument.business_summary,
            )
            self.session.add(existing)
            await self.session.flush()
        else:
            existing.name = instrument.name
            existing.sector = instrument.sector
            existing.exchange = instrument.exchange
            existing.cik = instrument.cik
            # Only overwrite an existing summary if a new one is provided —
            # preserves descriptions across snapshot-only re-ingests.
            if instrument.business_summary:
                existing.business_summary = instrument.business_summary
        return existing

    async def get_by_ticker(self, ticker: str) -> Instrument | None:
        """Return the instrument matching ``ticker`` (case-insensitive) or None."""
        row = await self.session.scalar(
            select(InstrumentRow).where(InstrumentRow.ticker == ticker.upper())
        )
        return _to_instrument(row) if row else None

    async def list_all(self) -> list[Instrument]:
        """Return every instrument, alphabetised by ticker."""
        rows = (
            await self.session.scalars(select(InstrumentRow).order_by(InstrumentRow.ticker))
        ).all()
        return [_to_instrument(r) for r in rows]


class FundamentalsRepository:
    """CRUD over the ``fundamentals_snapshots`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, instrument_id: int, snapshot: FundamentalsSnapshot) -> None:
        """Insert or update the snapshot for ``(instrument_id, snapshot.as_of)``.

        Dispatches on the active dialect because Postgres and SQLite use
        different ``INSERT ... ON CONFLICT`` syntaxes; SQLAlchemy can't paper
        over that with a single statement builder.
        """
        bind = self.session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""

        values = {
            "instrument_id": instrument_id,
            "as_of": snapshot.as_of,
            "market_cap_usd": snapshot.market_cap_usd,
            "revenue_growth_pct": snapshot.revenue_growth_pct,
            "gross_margin_pct": snapshot.gross_margin_pct,
            "net_debt_to_ebitda": snapshot.net_debt_to_ebitda,
            "fcf_yield_pct": snapshot.fcf_yield_pct,
            "price_usd": snapshot.price_usd,
            "revenue_ttm_usd": snapshot.revenue_ttm_usd,
            "ebitda_ttm_usd": snapshot.ebitda_ttm_usd,
        }
        update_cols = {k: v for k, v in values.items() if k not in {"instrument_id", "as_of"}}

        if dialect_name == "postgresql":
            pg_stmt = pg_insert(FundamentalsRow).values(**values)
            pg_stmt = pg_stmt.on_conflict_do_update(
                index_elements=["instrument_id", "as_of"], set_=update_cols
            )
            await self.session.execute(pg_stmt)
        elif dialect_name == "sqlite":
            sqlite_stmt = sqlite_insert(FundamentalsRow).values(**values)
            sqlite_stmt = sqlite_stmt.on_conflict_do_update(
                index_elements=["instrument_id", "as_of"], set_=update_cols
            )
            await self.session.execute(sqlite_stmt)
        else:  # pragma: no cover - defensive fallback
            raise RuntimeError(f"Unsupported dialect for upsert: {dialect_name}")

    async def latest_for_all(self) -> list[tuple[Instrument, FundamentalsSnapshot]]:
        """Return the most recent snapshot for every instrument that has one."""
        stmt = (
            select(InstrumentRow, FundamentalsRow)
            .join(FundamentalsRow, FundamentalsRow.instrument_id == InstrumentRow.id)
            .order_by(InstrumentRow.ticker, FundamentalsRow.as_of.desc())
        )
        seen: set[str] = set()
        out: list[tuple[Instrument, FundamentalsSnapshot]] = []
        for inst_row, fund_row in (await self.session.execute(stmt)).all():
            if inst_row.ticker in seen:
                continue
            seen.add(inst_row.ticker)
            out.append((_to_instrument(inst_row), _to_snapshot(fund_row, inst_row.ticker)))
        return out

    async def history_for_ticker(
        self, ticker: str, *, limit: int | None = None
    ) -> list[FundamentalsSnapshot]:
        """Return all snapshots for ``ticker`` ordered by ``as_of`` ascending.

        Use the ascending order so the caller can feed the list directly into
        a time-series chart. Pass ``limit`` to cap the number of points
        returned (the *most recent* ``limit`` are kept).
        """
        ticker = ticker.upper()
        stmt = (
            select(InstrumentRow, FundamentalsRow)
            .join(FundamentalsRow, FundamentalsRow.instrument_id == InstrumentRow.id)
            .where(InstrumentRow.ticker == ticker)
            .order_by(FundamentalsRow.as_of.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        snapshots = [_to_snapshot(fund, inst.ticker) for inst, fund in rows]
        if limit is not None and len(snapshots) > limit:
            snapshots = snapshots[-limit:]
        return snapshots

    async def history_for_all(self) -> dict[str, list[FundamentalsSnapshot]]:
        """Return a ``{ticker: [snapshots ascending by date]}`` map for every instrument."""
        stmt = (
            select(InstrumentRow, FundamentalsRow)
            .join(FundamentalsRow, FundamentalsRow.instrument_id == InstrumentRow.id)
            .order_by(InstrumentRow.ticker, FundamentalsRow.as_of.asc())
        )
        out: dict[str, list[FundamentalsSnapshot]] = {}
        for inst_row, fund_row in (await self.session.execute(stmt)).all():
            out.setdefault(inst_row.ticker, []).append(_to_snapshot(fund_row, inst_row.ticker))
        return out


class WatchlistRepository:
    """CRUD over the ``watchlist_entries`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, ticker: str, notes: str | None = None) -> None:
        """Add ``ticker`` to the watchlist, or update its notes if already present."""
        existing = await self.session.scalar(
            select(WatchlistRow).where(WatchlistRow.ticker == ticker.upper())
        )
        if existing is None:
            self.session.add(WatchlistRow(ticker=ticker.upper(), notes=notes))
        else:
            existing.notes = notes

    async def remove(self, ticker: str) -> bool:
        """Remove ``ticker`` from the watchlist. Returns True if a row was deleted."""
        row = await self.session.scalar(
            select(WatchlistRow).where(WatchlistRow.ticker == ticker.upper())
        )
        if row is None:
            return False
        await self.session.delete(row)
        return True

    async def list_tickers(self) -> list[str]:
        """Return every watchlisted ticker, alphabetised."""
        rows = (
            await self.session.scalars(select(WatchlistRow.ticker).order_by(WatchlistRow.ticker))
        ).all()
        return list(rows)
