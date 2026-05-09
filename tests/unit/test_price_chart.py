"""Tests for the PriceChart widget and the FMP price-history parser."""

from __future__ import annotations

from datetime import date

import pytest

from openbourse.tui.widgets.price_chart import PriceChart


def _series(start: date, n: int, base: float, slope: float) -> list[tuple[date, float]]:
    """Build an ``n``-point synthetic series starting at ``start`` + ``base`` $."""
    from datetime import timedelta

    return [(start + timedelta(days=i), base + slope * i) for i in range(n)]


class TestPriceChartRender:
    def test_insufficient_history_falls_back_to_message(self) -> None:
        chart = PriceChart("CDNS", [], chart_width=80)
        rendered = str(chart.render())
        assert "insufficient price history" in rendered

    def test_single_point_treated_as_insufficient(self) -> None:
        chart = PriceChart("CDNS", [(date(2025, 1, 1), 100.0)], chart_width=80)
        rendered = str(chart.render())
        assert "insufficient" in rendered

    def test_uptrend_renders_with_positive_change(self) -> None:
        points = _series(date(2023, 1, 1), n=200, base=100.0, slope=0.5)
        chart = PriceChart("UP", points, chart_width=120)
        rendered = str(chart.render())
        # Title should include a positive sign and the ticker.
        assert "UP" in rendered
        assert "+" in rendered  # positive change percent

    def test_downtrend_renders_with_negative_change(self) -> None:
        points = _series(date(2023, 1, 1), n=200, base=100.0, slope=-0.3)
        chart = PriceChart("DOWN", points, chart_width=120)
        rendered = str(chart.render())
        assert "DOWN" in rendered
        # The change-percent format includes a minus when descending.
        assert "-" in rendered


class TestFmpPriceParser:
    def test_period_to_days_handles_year_month_day(self) -> None:
        from openbourse.providers.fmp import _period_to_days

        assert _period_to_days("3y") == 1095
        assert _period_to_days("6mo") == 180
        assert _period_to_days("30d") == 30
        # Unknown formats fall back to a sensible default.
        assert _period_to_days("garbage") == 365 * 3

    def test_parse_fmp_prices_extracts_close_in_order(self) -> None:
        from openbourse.providers.fmp import _parse_fmp_prices

        # FMP returns rows in arbitrary order — parser must sort ascending.
        payload = [
            {"date": "2025-01-15", "close": 102.5},
            {"date": "2025-01-13", "close": 100.0},
            {"date": "2025-01-14", "close": 101.0},
            # Row missing close should drop without crashing.
            {"date": "2025-01-12"},
            # Use adjClose as a fallback when close is absent.
            {"date": "2025-01-10", "adjClose": 98.0},
        ]
        out = _parse_fmp_prices(payload)
        assert [d for d, _ in out] == [
            date(2025, 1, 10),
            date(2025, 1, 13),
            date(2025, 1, 14),
            date(2025, 1, 15),
        ]
        assert out[0] == (date(2025, 1, 10), 98.0)

    def test_parse_fmp_prices_handles_garbage(self) -> None:
        from openbourse.providers.fmp import _parse_fmp_prices

        assert _parse_fmp_prices([]) == []
        assert _parse_fmp_prices([{"date": "not-a-date", "close": 1.0}]) == []


class TestStubPriceHistory:
    async def test_known_ticker_returns_seed_prices(self) -> None:
        from openbourse.providers.fmp import StubFundamentalsProvider

        provider = StubFundamentalsProvider()
        history = await provider.price_history("CDNS", period="3y")
        # CDNS is in the seed and has a price on its latest snapshot.
        assert len(history) >= 1
        assert all(isinstance(d, date) and price > 0 for d, price in history)

    async def test_unknown_ticker_returns_empty(self) -> None:
        from openbourse.providers.fmp import StubFundamentalsProvider

        provider = StubFundamentalsProvider()
        assert await provider.price_history("ZZZZ", period="3y") == []


def test_chart_handles_zero_initial_price() -> None:
    """Avoid ZeroDivisionError when prices[0] is zero."""
    chart = PriceChart("X", [(date(2025, 1, 1), 0.0), (date(2025, 6, 1), 100.0)])
    # Just rendering shouldn't crash — fallback shows 0 in the change pct.
    rendered = str(chart.render())
    assert "X" in rendered


# Mark async tests so pytest-asyncio picks them up under our auto mode.
pytest.importorskip("pytest_asyncio")
