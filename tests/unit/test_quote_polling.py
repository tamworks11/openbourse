"""Tests for the viewport-aware quote-polling row selector."""

from __future__ import annotations

from datetime import UTC, date, datetime

from openbourse.domain import Candidate, FundamentalsSnapshot, Instrument, Quote, Verdict
from openbourse.tui.screens.screener import (
    _detail_row,
    _format_change,
    _format_pe,
    _format_signed_pct_opt,
    _format_volume,
    _select_tickers_to_poll,
)


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


class TestFormatVolume:
    def test_none_renders_as_em_dash(self) -> None:
        assert _format_volume(None) == "—"

    def test_billions(self) -> None:
        assert _format_volume(1_400_000_000) == "1.40B"

    def test_millions(self) -> None:
        assert _format_volume(12_300_000) == "12.3M"

    def test_thousands(self) -> None:
        assert _format_volume(850_000) == "850K"

    def test_thousands_boundary_rounds_to_k(self) -> None:
        assert _format_volume(1_234) == "1K"

    def test_sub_thousand_renders_plain(self) -> None:
        assert _format_volume(999) == "999"
        assert _format_volume(0) == "0"


class TestVolumeColumn:
    def test_row_has_one_cell_per_column(self, stub_providers: object) -> None:
        from openbourse.tui.screens.screener import COLUMNS, ScreenerScreen

        screen = ScreenerScreen(providers=stub_providers)  # type: ignore[arg-type]
        row = screen._row_for(1, _candidate("AAPL"))
        assert len(row) == len(COLUMNS)

    def test_volume_cell_sits_at_volume_column_index(self, stub_providers: object) -> None:
        from openbourse.tui.screens.screener import COLUMNS, ScreenerScreen

        # The constant must point at the "VOLUME" header...
        assert COLUMNS[ScreenerScreen.VOLUME_COLUMN_INDEX] == "VOLUME"

        screen = ScreenerScreen(providers=stub_providers)  # type: ignore[arg-type]
        screen._latest_quotes["AAPL"] = Quote(
            ticker="AAPL",
            price_usd=190.0,
            fetched_at=datetime.now(UTC),
            volume=12_300_000,
        )
        row = screen._row_for(1, _candidate("AAPL"))
        # ...and the formatted volume must land in that cell.
        assert row[ScreenerScreen.VOLUME_COLUMN_INDEX] == "12.3M"

    def test_volume_cell_is_em_dash_before_any_poll(self, stub_providers: object) -> None:
        from openbourse.tui.screens.screener import ScreenerScreen

        screen = ScreenerScreen(providers=stub_providers)  # type: ignore[arg-type]
        row = screen._row_for(1, _candidate("MSFT"))
        assert row[ScreenerScreen.VOLUME_COLUMN_INDEX] == "—"


class TestFormatChange:
    def test_none_renders_as_em_dash(self) -> None:
        assert _format_change(None) == "—"

    def test_positive_change_is_signed(self) -> None:
        assert _format_change(2.34) == "+$2.34"

    def test_negative_change_is_signed(self) -> None:
        assert _format_change(-1.05) == "-$1.05"

    def test_zero_change_renders_as_positive(self) -> None:
        assert _format_change(0.0) == "+$0.00"


class TestFormatSignedPctOpt:
    def test_none_renders_as_em_dash(self) -> None:
        assert _format_signed_pct_opt(None) == "—"

    def test_positive_is_signed(self) -> None:
        assert _format_signed_pct_opt(18.4) == "+18.4%"

    def test_negative_is_signed(self) -> None:
        assert _format_signed_pct_opt(-3.2) == "-3.2%"


class TestFormatPe:
    def test_none_renders_as_em_dash(self) -> None:
        assert _format_pe(None) == "—"

    def test_positive_pe_to_one_decimal(self) -> None:
        assert _format_pe(28.43) == "28.4"

    def test_non_positive_pe_renders_as_em_dash(self) -> None:
        # A negative trailing P/E (loss-making TTM) is not a usable ratio.
        assert _format_pe(-12.0) == "—"
        assert _format_pe(0.0) == "—"


class TestDetailRow:
    def test_two_pairs_both_appear(self) -> None:
        line = _detail_row(("Price", "$10.00"), ("Volume", "1.2M"))
        assert "Price" in line
        assert "$10.00" in line
        assert "Volume" in line
        assert "1.2M" in line

    def test_single_pair_omits_the_second_cell(self) -> None:
        line = _detail_row(("FCF yield", "2.8%"), None)
        assert line.startswith("FCF yield")
        assert line.rstrip().endswith("2.8%")
