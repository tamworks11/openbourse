"""Tests for the risk-score module."""

from __future__ import annotations

from datetime import date

import pytest

from openbourse.domain import FundamentalsSnapshot
from openbourse.screening.risk import (
    RISK_MAX,
    RiskWeights,
    compute_risk_score,
    normalize_fcf_risk,
    normalize_leverage_risk,
    normalize_margin_risk,
    normalize_size_risk,
)


def _snap(**overrides: float) -> FundamentalsSnapshot:
    """Build a snapshot with sensible defaults; override fields per test."""
    base: dict[str, float | str | date] = {
        "ticker": "TEST",
        "as_of": date(2026, 1, 1),
        "market_cap_usd": 50_000_000_000.0,
        "revenue_growth_pct": 15.0,
        "gross_margin_pct": 60.0,
        "net_debt_to_ebitda": 1.0,
        "fcf_yield_pct": 4.0,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return FundamentalsSnapshot(**base)  # type: ignore[arg-type]


class TestNormalizers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(-2.0, 0.0), (0.0, 0.0), (2.5, 0.5), (5.0, 1.0), (8.0, 1.0)],
    )
    def test_normalize_leverage_risk(self, value: float, expected: float) -> None:
        assert normalize_leverage_risk(value) == pytest.approx(expected)

    def test_normalize_size_risk_below_1b_is_full(self) -> None:
        assert normalize_size_risk(500_000_000) == 1.0

    def test_normalize_size_risk_above_100b_is_zero(self) -> None:
        assert normalize_size_risk(500_000_000_000) == 0.0

    def test_normalize_size_risk_at_10b_is_midband(self) -> None:
        # log10(1e10) = 10, midpoint of [9, 11] log span -> 0.5.
        assert normalize_size_risk(10_000_000_000) == pytest.approx(0.5)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(-10.0, 1.0), (0.0, 1.0), (50.0, 0.5), (100.0, 0.0), (110.0, 0.0)],
    )
    def test_normalize_margin_risk(self, value: float, expected: float) -> None:
        assert normalize_margin_risk(value) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(-2.0, 1.0), (0.0, 1.0), (4.0, 0.5), (8.0, 0.0), (12.0, 0.0)],
    )
    def test_normalize_fcf_risk(self, value: float, expected: float) -> None:
        assert normalize_fcf_risk(value) == pytest.approx(expected)


class TestRiskWeights:
    def test_default_weights_sum_to_one(self) -> None:
        RiskWeights()  # validates in __post_init__

    def test_invalid_weights_raise(self) -> None:
        with pytest.raises(ValueError, match="weights must sum"):
            RiskWeights(leverage=0.5, size=0.5, margin=0.5, fcf_yield=0.5)


class TestComputeRiskScore:
    def test_score_in_range(self, sample_snapshot: FundamentalsSnapshot) -> None:
        score = compute_risk_score(sample_snapshot)
        assert 0 <= score <= RISK_MAX

    def test_score_is_integer(self, sample_snapshot: FundamentalsSnapshot) -> None:
        assert isinstance(compute_risk_score(sample_snapshot), int)

    def test_high_quality_compounder_is_low_risk(
        self, sample_snapshot: FundamentalsSnapshot
    ) -> None:
        # CDNS-like: $78B mkt cap, 89% margin, 0.2x leverage, 2.8% FCF yld.
        # Should land in the low-risk band (<=40).
        assert compute_risk_score(sample_snapshot) < 40

    def test_low_quality_name_is_high_risk(
        self, low_quality_snapshot: FundamentalsSnapshot
    ) -> None:
        # F-like: $48B mkt cap, 8.5% margin, 6.4x leverage, 4% FCF yld.
        # Should land in the high-risk band (>=60).
        assert compute_risk_score(low_quality_snapshot) >= 60

    def test_perfect_safety_floor(self) -> None:
        # Mega-cap, no debt, fat margin, healthy FCF -> near zero risk.
        snap = _snap(
            market_cap_usd=500_000_000_000,
            net_debt_to_ebitda=0.0,
            gross_margin_pct=80.0,
            fcf_yield_pct=8.0,
        )
        assert compute_risk_score(snap) <= 5

    def test_worst_case_ceiling(self) -> None:
        # Tiny, broke, levered, no FCF -> near 100.
        snap = _snap(
            market_cap_usd=500_000_000,
            net_debt_to_ebitda=8.0,
            gross_margin_pct=5.0,
            fcf_yield_pct=-2.0,
        )
        assert compute_risk_score(snap) >= 95

    def test_custom_weights_change_score(
        self, sample_snapshot: FundamentalsSnapshot
    ) -> None:
        # Heavy weight on size shifts CDNS (mid-cap) higher than the default.
        size_heavy = RiskWeights(leverage=0.1, size=0.7, margin=0.1, fcf_yield=0.1)
        balanced = compute_risk_score(sample_snapshot)
        skewed = compute_risk_score(sample_snapshot, size_heavy)
        # CDNS at $78B is closer to 0 size-risk than 1, but still nonzero;
        # the size-heavy weight should pull the composite below the
        # balanced default (which gets pulled up by FCF yield risk).
        assert skewed < balanced
