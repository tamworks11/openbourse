"""Tests for the scoring module."""

from __future__ import annotations

from datetime import date

import pytest

from openbourse.domain import FundamentalsSnapshot, Verdict
from openbourse.screening.scoring import (
    SCORE_MAX,
    Weights,
    composite_score,
    normalize_fcf_yield,
    normalize_growth,
    normalize_leverage,
    normalize_margin,
    normalize_size,
    verdict_for,
)


class TestNormalizers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(-5.0, 0.0), (0.0, 0.0), (15.0, 0.5), (30.0, 1.0), (50.0, 1.0)],
    )
    def test_normalize_growth(self, value: float, expected: float) -> None:
        assert normalize_growth(value) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(-5.0, 0.0), (0.0, 0.0), (50.0, 0.5), (100.0, 1.0), (110.0, 1.0)],
    )
    def test_normalize_margin(self, value: float, expected: float) -> None:
        assert normalize_margin(value) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0.0, 1.0), (1.5, 0.5), (3.0, 0.0), (6.0, 0.0)],
    )
    def test_normalize_leverage(self, value: float, expected: float) -> None:
        assert normalize_leverage(value) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(-1.0, 0.0), (0.0, 0.0), (4.0, 0.5), (8.0, 1.0), (12.0, 1.0)],
    )
    def test_normalize_fcf_yield(self, value: float, expected: float) -> None:
        assert normalize_fcf_yield(value) == pytest.approx(expected)

    def test_normalize_size_below_one_billion_is_zero(self) -> None:
        assert normalize_size(500_000_000) == 0.0

    def test_normalize_size_at_100b_is_one(self) -> None:
        assert normalize_size(100_000_000_000) == pytest.approx(1.0)

    def test_normalize_size_caps_at_one(self) -> None:
        assert normalize_size(5_000_000_000_000) == 1.0


class TestWeights:
    def test_default_weights_sum_to_one(self) -> None:
        Weights()  # validates in __post_init__

    def test_invalid_weights_raise(self) -> None:
        with pytest.raises(ValueError, match="weights must sum"):
            Weights(growth=0.5, margin=0.5, leverage=0.5, fcf_yield=0.5, size=0.5)


class TestCompositeScore:
    def test_score_in_zero_hundred_range(self) -> None:
        snap = FundamentalsSnapshot(
            ticker="X",
            as_of=date(2026, 1, 1),
            market_cap_usd=10_000_000_000,
            revenue_growth_pct=10.0,
            gross_margin_pct=50.0,
            net_debt_to_ebitda=1.0,
            fcf_yield_pct=2.0,
        )
        score = composite_score(snap)
        assert 0 <= score <= SCORE_MAX

    def test_quality_compounder_scores_high(self, sample_snapshot: FundamentalsSnapshot) -> None:
        # CDNS-like inputs should land in the INTERESTING/STRONG_INTEREST band.
        score = composite_score(sample_snapshot)
        assert score >= 70

    def test_low_quality_scores_low(self, low_quality_snapshot: FundamentalsSnapshot) -> None:
        # Ford-like inputs should land below the PASS threshold.
        score = composite_score(low_quality_snapshot)
        assert score < 70

    def test_score_is_integer(self, sample_snapshot: FundamentalsSnapshot) -> None:
        score = composite_score(sample_snapshot)
        assert isinstance(score, int)


class TestVerdict:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (100, Verdict.STRONG_INTEREST),
            (90, Verdict.STRONG_INTEREST),
            (89, Verdict.INTERESTING),
            (80, Verdict.INTERESTING),
            (79, Verdict.PASS),
            (70, Verdict.PASS),
            (69, Verdict.REJECT),
            (0, Verdict.REJECT),
        ],
    )
    def test_thresholds(self, score: int, expected: Verdict) -> None:
        assert verdict_for(score) == expected
