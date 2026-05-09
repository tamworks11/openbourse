"""Tests for the style-fit score module."""

from __future__ import annotations

from datetime import date

import pytest

from openbourse.domain import FundamentalsSnapshot, ScreenDefinition
from openbourse.screening.fit import compute_style_fit


def _snap(**overrides: float) -> FundamentalsSnapshot:
    """Build a snapshot with sane defaults; override one or two fields per test."""
    base: dict[str, float | str | date] = {
        "ticker": "TEST",
        "as_of": date(2026, 1, 1),
        "market_cap_usd": 50_000_000_000.0,
        "revenue_growth_pct": 15.0,
        "gross_margin_pct": 60.0,
        "net_debt_to_ebitda": 1.0,
        "fcf_yield_pct": 3.0,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return FundamentalsSnapshot(**base)  # type: ignore[arg-type]


class TestStyleFitWithNoCriteria:
    def test_empty_screen_returns_full_credit(self) -> None:
        screen = ScreenDefinition(name="empty", description="")
        assert compute_style_fit(_snap(), screen) == 100.0


class TestStyleFitWithMinThresholds:
    def test_value_at_threshold_scores_50(self) -> None:
        screen = ScreenDefinition(name="growth", description="", min_revenue_growth_pct=15.0)
        assert compute_style_fit(_snap(revenue_growth_pct=15.0), screen) == pytest.approx(50.0)

    def test_value_well_above_threshold_scores_100(self) -> None:
        screen = ScreenDefinition(name="growth", description="", min_revenue_growth_pct=15.0)
        # 30% maps to soft_ceiling.
        assert compute_style_fit(_snap(revenue_growth_pct=30.0), screen) == pytest.approx(100.0)

    def test_value_below_threshold_scores_under_50(self) -> None:
        screen = ScreenDefinition(name="growth", description="", min_revenue_growth_pct=15.0)
        score = compute_style_fit(_snap(revenue_growth_pct=7.5), screen)
        assert score == pytest.approx(25.0)  # halfway between 0 and 50

    def test_zero_value_scores_zero(self) -> None:
        screen = ScreenDefinition(name="growth", description="", min_revenue_growth_pct=15.0)
        assert compute_style_fit(_snap(revenue_growth_pct=0.0), screen) == 0.0


class TestStyleFitWithMaxThreshold:
    def test_zero_leverage_scores_100(self) -> None:
        screen = ScreenDefinition(name="leverage", description="", max_net_debt_to_ebitda=2.0)
        assert compute_style_fit(_snap(net_debt_to_ebitda=0.0), screen) == 100.0

    def test_at_threshold_scores_50(self) -> None:
        screen = ScreenDefinition(name="leverage", description="", max_net_debt_to_ebitda=2.0)
        assert compute_style_fit(_snap(net_debt_to_ebitda=2.0), screen) == pytest.approx(50.0)

    def test_well_above_threshold_scores_zero(self) -> None:
        screen = ScreenDefinition(name="leverage", description="", max_net_debt_to_ebitda=2.0)
        # 4x debt is at 2x threshold = soft_ceiling -> 0.
        assert compute_style_fit(_snap(net_debt_to_ebitda=4.0), screen) == 0.0


class TestStyleFitAcrossMultipleCriteria:
    def test_average_of_per_criterion_fits(self) -> None:
        # Growth at threshold (50) and margin well above (100) → average 75.
        screen = ScreenDefinition(
            name="multi",
            description="",
            min_revenue_growth_pct=15.0,
            min_gross_margin_pct=40.0,
        )
        snap = _snap(revenue_growth_pct=15.0, gross_margin_pct=60.0)
        assert compute_style_fit(snap, screen) == pytest.approx(75.0)

    def test_perfect_candidate_scores_100(self) -> None:
        screen = ScreenDefinition(
            name="quality",
            description="",
            min_revenue_growth_pct=15.0,
            min_gross_margin_pct=40.0,
            max_net_debt_to_ebitda=1.0,
        )
        snap = _snap(revenue_growth_pct=40.0, gross_margin_pct=90.0, net_debt_to_ebitda=0.0)
        assert compute_style_fit(snap, screen) == pytest.approx(100.0)
