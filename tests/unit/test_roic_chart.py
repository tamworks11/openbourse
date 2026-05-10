"""Tests for the ROIC chart widget and the synthetic-ROIC helper."""

from __future__ import annotations

from datetime import date

from openbourse.domain import FundamentalsSnapshot
from openbourse.providers.fmp import _synthetic_roic
from openbourse.tui.widgets.roic_chart import RoicChart


def _snap(year: int, roic: float) -> FundamentalsSnapshot:
    """Build a minimal snapshot pinned to ``year-12-31`` with the given ROIC."""
    return FundamentalsSnapshot(
        ticker="X",
        as_of=date(year, 12, 31),
        market_cap_usd=1e10,
        revenue_growth_pct=0.0,
        gross_margin_pct=0.0,
        net_debt_to_ebitda=0.0,
        fcf_yield_pct=0.0,
        roic_pct=roic,
    )


class TestRoicChartRender:
    def test_no_history_falls_back_to_message(self) -> None:
        chart = RoicChart([], chart_width=70)
        rendered = str(chart.render())
        assert "insufficient history" in rendered

    def test_single_point_treated_as_insufficient(self) -> None:
        chart = RoicChart([_snap(2024, 18.0)], chart_width=70)
        rendered = str(chart.render())
        assert "insufficient" in rendered

    def test_zeros_are_dropped_before_chart_renders(self) -> None:
        # Two snapshots, both with ROIC=0 → effectively empty for the chart.
        chart = RoicChart([_snap(2023, 0.0), _snap(2024, 0.0)], chart_width=70)
        rendered = str(chart.render())
        assert "insufficient" in rendered

    def test_renders_when_two_or_more_valid_points(self) -> None:
        chart = RoicChart(
            [_snap(2022, 14.0), _snap(2023, 18.0), _snap(2024, 22.0)],
            chart_width=70,
        )
        rendered = str(chart.render())
        # Title carries the latest ROIC; current value shows up in the title.
        assert "ROIC" in rendered
        assert "22.0" in rendered or "22.0%" in rendered

    def test_title_includes_change_in_percentage_points(self) -> None:
        chart = RoicChart(
            [_snap(2022, 12.0), _snap(2024, 22.0)],
            chart_width=70,
        )
        rendered = str(chart.render())
        # 22 - 12 = +10pp.
        assert "+10.0pp" in rendered or "+10.0" in rendered


class TestSyntheticRoic:
    def test_high_quality_compounder_lands_above_15(self) -> None:
        # 80% gross margin + 5% FCF yield → quality compounder territory.
        assert _synthetic_roic(80.0, 5.0) > 15.0

    def test_low_quality_lands_below_10(self) -> None:
        # 8% gross margin + 0% FCF yield → low-margin commodity business.
        assert _synthetic_roic(8.0, 0.0) < 10.0

    def test_capped_at_60(self) -> None:
        # Even unrealistic inputs shouldn't blow up the chart's y-axis.
        assert _synthetic_roic(200.0, 50.0) == 60.0

    def test_floored_at_zero(self) -> None:
        # Negative inputs (e.g. cash-burning company) clamp to 0, not below.
        assert _synthetic_roic(-10.0, -5.0) == 0.0
