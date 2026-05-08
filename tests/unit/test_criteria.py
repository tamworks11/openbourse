"""Tests for screen definitions and the filter predicate."""

from __future__ import annotations

from dataclasses import replace

from openbourse.domain import FundamentalsSnapshot
from openbourse.screening.criteria import BUILTIN_SCREENS, passes_screen


def test_quality_compounders_screen_passes_high_quality(
    sample_snapshot: FundamentalsSnapshot,
) -> None:
    assert passes_screen(sample_snapshot, BUILTIN_SCREENS["quality_compounders"])


def test_quality_compounders_screen_rejects_low_quality(
    low_quality_snapshot: FundamentalsSnapshot,
) -> None:
    assert not passes_screen(low_quality_snapshot, BUILTIN_SCREENS["quality_compounders"])


def test_growth_threshold_is_inclusive(sample_snapshot: FundamentalsSnapshot) -> None:
    screen = BUILTIN_SCREENS["quality_compounders"]
    snap = replace(sample_snapshot, revenue_growth_pct=screen.min_revenue_growth_pct)
    assert passes_screen(snap, screen)


def test_growth_below_threshold_rejects(sample_snapshot: FundamentalsSnapshot) -> None:
    screen = BUILTIN_SCREENS["quality_compounders"]
    snap = replace(sample_snapshot, revenue_growth_pct=screen.min_revenue_growth_pct - 0.1)
    assert not passes_screen(snap, screen)


def test_leverage_above_max_rejects(sample_snapshot: FundamentalsSnapshot) -> None:
    screen = BUILTIN_SCREENS["quality_compounders"]
    snap = replace(sample_snapshot, net_debt_to_ebitda=screen.max_net_debt_to_ebitda + 0.1)
    assert not passes_screen(snap, screen)


def test_market_cap_below_min_rejects(sample_snapshot: FundamentalsSnapshot) -> None:
    screen = BUILTIN_SCREENS["quality_compounders"]
    snap = replace(sample_snapshot, market_cap_usd=screen.min_market_cap_usd - 1)
    assert not passes_screen(snap, screen)


def test_deep_value_screen_requires_high_fcf_yield(
    sample_snapshot: FundamentalsSnapshot,
) -> None:
    # Sample snapshot has 2.8% fcf yield — too low for deep value.
    assert not passes_screen(sample_snapshot, BUILTIN_SCREENS["deep_value"])


def test_high_growth_screen_requires_25_pct_growth(
    sample_snapshot: FundamentalsSnapshot,
) -> None:
    # Sample snapshot has 18.4% growth — too low for high growth.
    assert not passes_screen(sample_snapshot, BUILTIN_SCREENS["high_growth"])
