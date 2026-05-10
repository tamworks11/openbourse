"""Tests for the viewport-aware quote-polling row selector."""

from __future__ import annotations

from datetime import date

from openbourse.domain import Candidate, FundamentalsSnapshot, Instrument, Verdict
from openbourse.tui.screens.screener import _select_tickers_to_poll


def _candidate(ticker: str) -> Candidate:
    """Minimal Candidate sufficient for the row-selector contract."""
    snap = FundamentalsSnapshot(
        ticker=ticker,
        as_of=date(2026, 1, 1),
        market_cap_usd=10_000_000_000.0,
        revenue_growth_pct=0.0,
        gross_margin_pct=0.0,
        net_debt_to_ebitda=0.0,
        fcf_yield_pct=0.0,
    )
    return Candidate(
        instrument=Instrument(ticker=ticker, name=ticker),
        snapshot=snap,
        score=0,
        verdict=Verdict.PASS,
    )


def _candidates(n: int) -> list[Candidate]:
    return [_candidate(f"T{i:04d}") for i in range(n)]


class TestSelectTickersToPoll:
    def test_empty_list_returns_empty(self) -> None:
        assert (
            _select_tickers_to_poll(
                [], visible_first=0, visible_last=10, cursor=None, padding=0, cap=100
            )
            == []
        )

    def test_visible_window_no_padding(self) -> None:
        cs = _candidates(100)
        out = _select_tickers_to_poll(
            cs, visible_first=10, visible_last=15, cursor=None, padding=0, cap=100
        )
        assert out == ["T0010", "T0011", "T0012", "T0013", "T0014"]

    def test_padding_extends_above_and_below(self) -> None:
        cs = _candidates(100)
        out = _select_tickers_to_poll(
            cs, visible_first=20, visible_last=25, cursor=None, padding=3, cap=100
        )
        # 20-3=17 inclusive, 25+3=28 exclusive → indices 17..27
        assert out[0] == "T0017"
        assert out[-1] == "T0027"
        assert len(out) == 11

    def test_padding_clamps_to_zero_at_top(self) -> None:
        cs = _candidates(100)
        out = _select_tickers_to_poll(
            cs, visible_first=2, visible_last=5, cursor=None, padding=10, cap=100
        )
        # 2-10 clamps to 0; 5+10=15 exclusive
        assert out[0] == "T0000"
        assert out[-1] == "T0014"

    def test_padding_clamps_to_total_at_bottom(self) -> None:
        cs = _candidates(50)
        out = _select_tickers_to_poll(
            cs, visible_first=45, visible_last=50, cursor=None, padding=20, cap=100
        )
        # 45-20=25 inclusive; 50+20=70 clamps to 50
        assert out[0] == "T0025"
        assert out[-1] == "T0049"
        assert "T0050" not in out

    def test_cursor_is_always_included(self) -> None:
        cs = _candidates(500)
        # Viewport at top, cursor jumped to row 400.
        out = _select_tickers_to_poll(
            cs, visible_first=0, visible_last=30, cursor=400, padding=5, cap=100
        )
        assert "T0400" in out

    def test_cursor_outside_range_is_ignored(self) -> None:
        cs = _candidates(50)
        out = _select_tickers_to_poll(
            cs, visible_first=0, visible_last=10, cursor=999, padding=0, cap=100
        )
        # Cursor index 999 doesn't exist; helper must not include "T0999".
        assert all(t.startswith("T") for t in out)
        assert "T0999" not in out

    def test_cap_limits_long_viewports(self) -> None:
        cs = _candidates(500)
        # Imagine a freakishly tall terminal showing 200 rows.
        out = _select_tickers_to_poll(
            cs, visible_first=0, visible_last=200, cursor=None, padding=0, cap=100
        )
        assert len(out) == 100

    def test_cap_keeps_lowest_indices_first(self) -> None:
        # Stable sorted output — caller can rely on order matching the table.
        cs = _candidates(200)
        out = _select_tickers_to_poll(
            cs, visible_first=50, visible_last=150, cursor=None, padding=0, cap=100
        )
        assert out[0] == "T0050"
        assert out[-1] == "T0149"

    def test_visible_last_equal_to_first_treated_as_empty_window(self) -> None:
        cs = _candidates(100)
        out = _select_tickers_to_poll(
            cs, visible_first=10, visible_last=10, cursor=42, padding=0, cap=100
        )
        # Empty visible window; only the cursor's row should land in the result.
        assert out == ["T0042"]
