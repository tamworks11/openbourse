"""Tests for fundamentals history: repository, seed loader, charts widget."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from openbourse.cli import _seed_history, _seed_universe
from openbourse.db.repositories import FundamentalsRepository, InstrumentRepository
from openbourse.domain import FundamentalsSnapshot, Instrument
from openbourse.tui.widgets.history_charts import _render_chart


def _snap(ticker: str, year: int, month: int, growth: float) -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        ticker=ticker,
        as_of=date(year, month, 30),
        market_cap_usd=1e10,
        revenue_growth_pct=growth,
        gross_margin_pct=70.0,
        net_debt_to_ebitda=0.5,
        fcf_yield_pct=2.5,
    )


class TestHistoryRepository:
    async def test_history_for_ticker_returns_ascending_by_date(
        self, db_session: AsyncSession
    ) -> None:
        instr_repo = InstrumentRepository(db_session)
        fund_repo = FundamentalsRepository(db_session)
        inst = await instr_repo.upsert(Instrument(ticker="CDNS", name="Cadence"))
        await db_session.flush()
        await fund_repo.upsert(inst.id, _snap("CDNS", 2025, 1, 14.0))
        await fund_repo.upsert(inst.id, _snap("CDNS", 2024, 7, 12.0))
        await fund_repo.upsert(inst.id, _snap("CDNS", 2025, 7, 16.0))
        await db_session.commit()

        history = await fund_repo.history_for_ticker("CDNS")
        assert [s.as_of for s in history] == [
            date(2024, 7, 30),
            date(2025, 1, 30),
            date(2025, 7, 30),
        ]

    async def test_history_for_ticker_respects_limit(self, db_session: AsyncSession) -> None:
        instr_repo = InstrumentRepository(db_session)
        fund_repo = FundamentalsRepository(db_session)
        inst = await instr_repo.upsert(Instrument(ticker="CDNS", name="Cadence"))
        await db_session.flush()
        for month in (1, 4, 7, 10):
            await fund_repo.upsert(inst.id, _snap("CDNS", 2025, month, 10.0 + month))
        await db_session.commit()

        latest_two = await fund_repo.history_for_ticker("CDNS", limit=2)
        assert len(latest_two) == 2
        assert latest_two[0].as_of == date(2025, 7, 30)
        assert latest_two[1].as_of == date(2025, 10, 30)

    async def test_history_for_unknown_ticker_is_empty(self, db_session: AsyncSession) -> None:
        history = await FundamentalsRepository(db_session).history_for_ticker("NOPE")
        assert history == []

    async def test_history_for_all_groups_by_ticker(self, db_session: AsyncSession) -> None:
        instr_repo = InstrumentRepository(db_session)
        fund_repo = FundamentalsRepository(db_session)
        cdns = await instr_repo.upsert(Instrument(ticker="CDNS", name="Cadence"))
        veev = await instr_repo.upsert(Instrument(ticker="VEEV", name="Veeva"))
        await db_session.flush()
        await fund_repo.upsert(cdns.id, _snap("CDNS", 2025, 1, 14.0))
        await fund_repo.upsert(cdns.id, _snap("CDNS", 2025, 7, 16.0))
        await fund_repo.upsert(veev.id, _snap("VEEV", 2025, 4, 15.0))
        await db_session.commit()

        history = await fund_repo.history_for_all()
        assert set(history) == {"CDNS", "VEEV"}
        assert len(history["CDNS"]) == 2
        assert len(history["VEEV"]) == 1
        assert history["CDNS"][0].as_of < history["CDNS"][1].as_of


class TestSeedLoader:
    def test_seed_universe_returns_one_pair_per_instrument(self) -> None:
        universe = _seed_universe()
        tickers = {pair[0].ticker for pair in universe}
        assert "CDNS" in tickers
        assert len(universe) == len(tickers)  # one row per ticker

    def test_seed_universe_pair_uses_latest_snapshot(self) -> None:
        universe = _seed_universe()
        cdns = next(pair for pair in universe if pair[0].ticker == "CDNS")
        # Latest seeded CDNS snapshot is 2026-04-30.
        assert cdns[1].as_of == date(2026, 4, 30)

    def test_seed_history_has_multiple_quarters(self) -> None:
        history = _seed_history()
        assert len(history["CDNS"]) >= 8
        # Ascending order by date.
        dates = [s.as_of for s in history["CDNS"]]
        assert dates == sorted(dates)


class TestHistoryChartsRendering:
    def test_render_chart_with_history_returns_string(self) -> None:
        snaps = [_snap("CDNS", 2025, m, 10.0 + m) for m in (1, 4, 7, 10)]
        out = _render_chart(
            "Revenue growth %",
            snaps,
            lambda s: s.revenue_growth_pct,
            "green",
            width=40,
            height=8,
        )
        assert isinstance(out, str)
        assert "Revenue growth" in out

    def test_render_chart_with_one_snapshot_falls_back_to_message(self) -> None:
        snaps = [_snap("CDNS", 2025, 1, 14.0)]
        out = _render_chart(
            "Revenue growth %",
            snaps,
            lambda s: s.revenue_growth_pct,
            "green",
            width=40,
            height=8,
        )
        assert "insufficient history" in out

    def test_render_chart_with_empty_history_falls_back_to_message(self) -> None:
        out = _render_chart(
            "Revenue growth %",
            [],
            lambda s: s.revenue_growth_pct,
            "green",
            width=40,
            height=8,
        )
        assert "insufficient history" in out
