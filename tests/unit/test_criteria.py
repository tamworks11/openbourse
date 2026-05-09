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


def test_all_screen_passes_every_snapshot(
    sample_snapshot: FundamentalsSnapshot,
    low_quality_snapshot: FundamentalsSnapshot,
) -> None:
    """The 'all' screen has every threshold None — nothing is excluded."""
    assert passes_screen(sample_snapshot, BUILTIN_SCREENS["all"])
    assert passes_screen(low_quality_snapshot, BUILTIN_SCREENS["all"])


def test_format_active_filters_renders_verdict_set() -> None:
    """The verdict filter shows up in the active-filters string."""
    from openbourse.domain import Verdict
    from openbourse.screening.criteria import format_active_filters

    base = BUILTIN_SCREENS["quality_compounders"]
    line = format_active_filters(base)
    assert "verdict" not in line  # default has verdicts=None

    with_verdicts = replace(
        base, verdicts=frozenset({Verdict.STRONG_INTEREST, Verdict.INTERESTING})
    )
    line = format_active_filters(with_verdicts)
    # Order follows declaration order, not set iteration.
    assert "verdict ∈ {STRONG_INTEREST, INTERESTING}" in line


def test_disabling_individual_filters_relaxes_only_that_one(
    low_quality_snapshot: FundamentalsSnapshot,
) -> None:
    """Setting one threshold to None lets a row pass that criterion only."""
    base = BUILTIN_SCREENS["quality_compounders"]
    # low_quality_snapshot: rev_growth 3.1, GM 8.5, leverage 6.4, mcap 48B, fcf 4.0
    assert not passes_screen(low_quality_snapshot, base)

    # Disable just leverage — still fails on rev_growth and GM.
    no_leverage = replace(base, max_net_debt_to_ebitda=None)
    assert not passes_screen(low_quality_snapshot, no_leverage)

    # Disable everything except market_cap (which low-quality already passes).
    almost_all_off = replace(
        base,
        min_revenue_growth_pct=None,
        min_gross_margin_pct=None,
        max_net_debt_to_ebitda=None,
        min_fcf_yield_pct=None,
    )
    assert passes_screen(low_quality_snapshot, almost_all_off)
