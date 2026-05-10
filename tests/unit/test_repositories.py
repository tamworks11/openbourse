"""Repository tests against an in-memory SQLite database."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from openbourse.db.repositories import (
    FundamentalsRepository,
    InstrumentRepository,
    WatchlistRepository,
)
from openbourse.domain import FundamentalsSnapshot, Instrument


async def test_instrument_upsert_inserts_and_returns(db_session: AsyncSession) -> None:
    repo = InstrumentRepository(db_session)
    inst = Instrument(ticker="CDNS", name="Cadence")
    row = await repo.upsert(inst)
    await db_session.commit()
    assert row.id is not None
    assert row.ticker == "CDNS"


async def test_instrument_upsert_updates_existing(db_session: AsyncSession) -> None:
    repo = InstrumentRepository(db_session)
    await repo.upsert(Instrument(ticker="CDNS", name="Old"))
    await db_session.commit()
    row = await repo.upsert(Instrument(ticker="CDNS", name="Cadence Design Systems"))
    await db_session.commit()
    assert row.name == "Cadence Design Systems"


async def test_get_by_ticker_returns_domain_object(db_session: AsyncSession) -> None:
    repo = InstrumentRepository(db_session)
    await repo.upsert(Instrument(ticker="CDNS", name="Cadence"))
    await db_session.commit()
    found = await repo.get_by_ticker("CDNS")
    assert found is not None
    assert isinstance(found, Instrument)
    assert found.name == "Cadence"


async def test_get_by_ticker_missing_returns_none(db_session: AsyncSession) -> None:
    repo = InstrumentRepository(db_session)
    assert await repo.get_by_ticker("NOPE") is None


async def test_fundamentals_upsert_round_trip(
    db_session: AsyncSession, sample_snapshot: FundamentalsSnapshot
) -> None:
    instr_repo = InstrumentRepository(db_session)
    fund_repo = FundamentalsRepository(db_session)
    inst_row = await instr_repo.upsert(Instrument(ticker="CDNS", name="Cadence"))
    await db_session.flush()
    await fund_repo.upsert(inst_row.id, sample_snapshot)
    await db_session.commit()

    pairs = await fund_repo.latest_for_all()
    assert len(pairs) == 1
    inst, snap = pairs[0]
    assert inst.ticker == "CDNS"
    assert snap.market_cap_usd == sample_snapshot.market_cap_usd


async def test_fundamentals_upsert_persists_all_metric_fields(
    db_session: AsyncSession,
) -> None:
    """Every field on FundamentalsSnapshot survives a DB round-trip.

    Regression test for the bug where ROIC was computed by the provider
    but silently dropped on insert because the column was missing —
    every new metric should ride this test or have its own.
    """
    from datetime import date

    instr_repo = InstrumentRepository(db_session)
    fund_repo = FundamentalsRepository(db_session)
    inst_row = await instr_repo.upsert(Instrument(ticker="X", name="X Corp"))
    await db_session.flush()

    written = FundamentalsSnapshot(
        ticker="X",
        as_of=date(2026, 1, 1),
        market_cap_usd=10e9,
        revenue_growth_pct=18.4,
        gross_margin_pct=89.1,
        net_debt_to_ebitda=0.2,
        fcf_yield_pct=2.8,
        price_usd=42.50,
        revenue_ttm_usd=5.4e9,
        ebitda_ttm_usd=1.8e9,
        roic_pct=22.7,
    )
    await fund_repo.upsert(inst_row.id, written)
    await db_session.commit()

    pairs = await fund_repo.latest_for_all()
    _, read = pairs[0]
    # Spot-check every field — anything dropped here will silently
    # break a downstream chart, so the round-trip is the right gate.
    assert read.roic_pct == 22.7
    assert read.price_usd == 42.50
    assert read.revenue_ttm_usd == 5.4e9
    assert read.ebitda_ttm_usd == 1.8e9
    assert read.market_cap_usd == 10e9
    assert read.gross_margin_pct == 89.1


async def test_fundamentals_upsert_updates_existing_row(
    db_session: AsyncSession, sample_snapshot: FundamentalsSnapshot
) -> None:
    instr_repo = InstrumentRepository(db_session)
    fund_repo = FundamentalsRepository(db_session)
    inst_row = await instr_repo.upsert(Instrument(ticker="CDNS", name="Cadence"))
    await db_session.flush()
    await fund_repo.upsert(inst_row.id, sample_snapshot)
    await db_session.commit()

    updated = FundamentalsSnapshot(
        ticker=sample_snapshot.ticker,
        as_of=sample_snapshot.as_of,
        market_cap_usd=99_000_000_000,
        revenue_growth_pct=20.0,
        gross_margin_pct=90.0,
        net_debt_to_ebitda=0.1,
        fcf_yield_pct=3.5,
    )
    await fund_repo.upsert(inst_row.id, updated)
    await db_session.commit()
    pairs = await fund_repo.latest_for_all()
    _, snap = pairs[0]
    assert snap.market_cap_usd == 99_000_000_000


async def test_latest_for_all_returns_most_recent_per_instrument(
    db_session: AsyncSession,
) -> None:
    instr_repo = InstrumentRepository(db_session)
    fund_repo = FundamentalsRepository(db_session)
    inst_row = await instr_repo.upsert(Instrument(ticker="CDNS", name="Cadence"))
    await db_session.flush()
    older = FundamentalsSnapshot(
        ticker="CDNS",
        as_of=date(2026, 1, 1),
        market_cap_usd=10.0,
        revenue_growth_pct=1.0,
        gross_margin_pct=1.0,
        net_debt_to_ebitda=0.0,
        fcf_yield_pct=0.0,
    )
    newer = FundamentalsSnapshot(
        ticker="CDNS",
        as_of=date(2026, 4, 30),
        market_cap_usd=20.0,
        revenue_growth_pct=2.0,
        gross_margin_pct=2.0,
        net_debt_to_ebitda=0.0,
        fcf_yield_pct=0.0,
    )
    await fund_repo.upsert(inst_row.id, older)
    await fund_repo.upsert(inst_row.id, newer)
    await db_session.commit()
    pairs = await fund_repo.latest_for_all()
    assert len(pairs) == 1
    assert pairs[0][1].as_of == date(2026, 4, 30)


async def test_watchlist_add_remove_list(db_session: AsyncSession) -> None:
    repo = WatchlistRepository(db_session)
    await repo.add("CDNS", notes="quality")
    await repo.add("VEEV")
    await db_session.commit()

    tickers = await repo.list_tickers()
    assert tickers == ["CDNS", "VEEV"]

    removed = await repo.remove("CDNS")
    await db_session.commit()
    assert removed is True
    assert await repo.list_tickers() == ["VEEV"]

    assert await repo.remove("NOPE") is False
