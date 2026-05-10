"""Tests for the valuation domain types — pure-function band math."""

from __future__ import annotations

from datetime import date

import pytest

from openbourse.domain import ValuationBand


def _hist(*pairs: tuple[int, float]) -> tuple[tuple[date, float], ...]:
    """Build a history tuple from ``(year, value)`` pairs."""
    return tuple((date(year, 12, 31), value) for year, value in pairs)


class TestValuationBandStats:
    def test_empty_history_returns_none_stats(self) -> None:
        band = ValuationBand(label="P/E", current=20.0)
        assert band.low is None
        assert band.high is None
        assert band.median is None
        assert band.has_history is False
        assert band.percentile_rank() is None

    def test_single_point_history_still_treated_as_no_band(self) -> None:
        band = ValuationBand(label="P/E", current=20.0, history=_hist((2024, 18.0)))
        # has_history requires >=2 points so the percentile range is meaningful.
        assert band.has_history is False

    def test_low_high_pick_extremes(self) -> None:
        band = ValuationBand(
            label="P/E",
            current=22.0,
            history=_hist((2021, 15.0), (2022, 25.0), (2023, 18.0), (2024, 30.0)),
        )
        assert band.low == 15.0
        assert band.high == 30.0

    def test_median_odd_count_picks_middle(self) -> None:
        band = ValuationBand(
            label="P/E",
            current=20.0,
            history=_hist((2021, 10.0), (2022, 20.0), (2023, 30.0)),
        )
        assert band.median == 20.0

    def test_median_even_count_averages_two_middle(self) -> None:
        band = ValuationBand(
            label="P/E",
            current=20.0,
            history=_hist((2021, 10.0), (2022, 20.0), (2023, 30.0), (2024, 40.0)),
        )
        # mid pair is (20, 30); average is 25.
        assert band.median == 25.0


class TestPercentileRank:
    def test_at_low_returns_zero(self) -> None:
        band = ValuationBand(
            label="P/E",
            current=10.0,
            history=_hist((2021, 10.0), (2022, 20.0), (2023, 30.0)),
        )
        assert band.percentile_rank() == 0.0

    def test_at_high_returns_hundred(self) -> None:
        band = ValuationBand(
            label="P/E",
            current=30.0,
            history=_hist((2021, 10.0), (2022, 20.0), (2023, 30.0)),
        )
        assert band.percentile_rank() == 100.0

    def test_at_midpoint_returns_fifty(self) -> None:
        band = ValuationBand(
            label="P/E",
            current=20.0,
            history=_hist((2021, 10.0), (2023, 30.0)),
        )
        assert band.percentile_rank() == 50.0

    def test_above_high_clamps_to_hundred(self) -> None:
        band = ValuationBand(
            label="P/E",
            current=50.0,
            history=_hist((2021, 10.0), (2023, 30.0)),
        )
        # Don't return >100 — the bar would overflow visually.
        assert band.percentile_rank() == 100.0

    def test_below_low_clamps_to_zero(self) -> None:
        band = ValuationBand(
            label="P/E",
            current=5.0,
            history=_hist((2021, 10.0), (2023, 30.0)),
        )
        assert band.percentile_rank() == 0.0

    def test_no_current_returns_none(self) -> None:
        band = ValuationBand(label="P/E", current=None, history=_hist((2021, 10.0), (2023, 30.0)))
        assert band.percentile_rank() is None

    def test_collapsed_range_returns_fifty(self) -> None:
        # All historical values identical — band is degenerate; convention
        # is to put the marker at 50% so the visual still renders something.
        band = ValuationBand(
            label="P/E",
            current=20.0,
            history=_hist((2021, 20.0), (2022, 20.0), (2023, 20.0)),
        )
        assert band.percentile_rank() == 50.0

    def test_quarter_point(self) -> None:
        band = ValuationBand(
            label="P/E",
            current=15.0,
            history=_hist((2021, 10.0), (2023, 30.0)),
        )
        # 15 is 25% of the way from 10 to 30.
        assert band.percentile_rank() == pytest.approx(25.0)


class TestParseFmpValuation:
    def test_current_only_when_history_endpoint_402s(self) -> None:
        """Free tier returns ``None`` for historical-key-metrics — bands carry
        current values but empty history. The panel must still render."""
        from openbourse.providers.fmp import _parse_fmp_valuation

        km_ttm = [
            {
                "peRatioTTM": 24.5,
                "enterpriseValueOverEBITDATTM": 18.2,
                "evToSalesTTM": 8.4,
                "priceToFreeCashFlowsRatioTTM": 32.1,
            }
        ]
        snapshot = _parse_fmp_valuation("CDNS", km_ttm, None)
        assert snapshot.ticker == "CDNS"
        labels = {b.label for b in snapshot.bands}
        assert labels == {"P/E", "EV/EBITDA", "EV/Revenue", "P/FCF"}
        for band in snapshot.bands:
            assert band.current is not None
            assert band.history == ()

    def test_historical_rows_populate_bands(self) -> None:
        from openbourse.providers.fmp import _parse_fmp_valuation

        km_ttm = [{"peRatioTTM": 24.5}]
        hist = [
            {"date": "2024-12-31", "peRatio": 28.0, "enterpriseValueOverEBITDA": 19.0},
            {"date": "2023-12-31", "peRatio": 22.0, "enterpriseValueOverEBITDA": 16.0},
            {"date": "2022-12-31", "peRatio": 18.0, "enterpriseValueOverEBITDA": 14.0},
        ]
        snapshot = _parse_fmp_valuation("CDNS", km_ttm, hist)
        pe = next(b for b in snapshot.bands if b.label == "P/E")
        # Three historical points; ascending by date.
        assert len(pe.history) == 3
        assert pe.history[0][0].year == 2022
        assert pe.history[-1][0].year == 2024

    def test_drops_zero_or_negative_historical_values(self) -> None:
        from openbourse.providers.fmp import _parse_fmp_valuation

        hist = [
            {"date": "2024-12-31", "peRatio": 0.0},  # dropped
            {"date": "2023-12-31", "peRatio": -5.0},  # dropped
            {"date": "2022-12-31", "peRatio": 18.0},  # kept
        ]
        snapshot = _parse_fmp_valuation("X", [], hist)
        pe = next(b for b in snapshot.bands if b.label == "P/E")
        assert len(pe.history) == 1
        assert pe.history[0][1] == 18.0

    def test_garbage_dates_are_skipped(self) -> None:
        from openbourse.providers.fmp import _parse_fmp_valuation

        hist = [
            {"date": "not-a-date", "peRatio": 20.0},
            {"date": "2024-12-31", "peRatio": 22.0},
        ]
        snapshot = _parse_fmp_valuation("X", [], hist)
        pe = next(b for b in snapshot.bands if b.label == "P/E")
        assert len(pe.history) == 1


class TestValuationPanelRender:
    """The widget renders to a Rich Text via render_panel_text — pure function."""

    def test_loading_state_when_snapshot_none(self) -> None:
        from openbourse.tui.widgets.valuation_panel import render_panel_text

        text = str(render_panel_text(None))
        assert "Valuation" in text
        assert "loading" in text

    def test_empty_bands_renders_no_data_message(self) -> None:
        from openbourse.domain import ValuationSnapshot
        from openbourse.tui.widgets.valuation_panel import render_panel_text

        snap = ValuationSnapshot(ticker="X", as_of=date(2026, 5, 9), bands=())
        text = str(render_panel_text(snap))
        assert "no data" in text

    def test_band_with_history_renders_full_row(self) -> None:
        from openbourse.domain import ValuationSnapshot
        from openbourse.tui.widgets.valuation_panel import render_panel_text

        snap = ValuationSnapshot(
            ticker="X",
            as_of=date(2026, 5, 9),
            bands=(
                ValuationBand(label="P/E", current=24.5, history=_hist((2021, 18.0), (2024, 30.0))),
            ),
        )
        text = str(render_panel_text(snap))
        # Current value, range, median should all surface.
        assert "24.5x" in text
        assert "18.0x" in text
        assert "30.0x" in text

    def test_band_without_history_collapses_to_no_band_message(self) -> None:
        from openbourse.domain import ValuationSnapshot
        from openbourse.tui.widgets.valuation_panel import render_panel_text

        snap = ValuationSnapshot(
            ticker="X",
            as_of=date(2026, 5, 9),
            bands=(ValuationBand(label="P/E", current=24.5),),
        )
        text = str(render_panel_text(snap))
        assert "24.5x" in text
        assert "no historical band" in text

    def test_missing_current_renders_dash(self) -> None:
        from openbourse.domain import ValuationSnapshot
        from openbourse.tui.widgets.valuation_panel import render_panel_text

        snap = ValuationSnapshot(
            ticker="X",
            as_of=date(2026, 5, 9),
            bands=(ValuationBand(label="P/E", current=None),),
        )
        text = str(render_panel_text(snap))
        assert "—" in text
