"""Tests for the screening orchestration service."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from openbourse.domain import FundamentalsSnapshot, Instrument, Verdict
from openbourse.screening import BUILTIN_SCREENS, ScreeningService


@pytest.fixture
def diverse_universe(
    sample_instrument: Instrument,
    sample_snapshot: FundamentalsSnapshot,
    low_quality_snapshot: FundamentalsSnapshot,
) -> list[tuple[Instrument, FundamentalsSnapshot]]:
    weak = Instrument(ticker="F", name="Ford Motor Company")
    middling_inst = Instrument(ticker="VEEV", name="Veeva Systems")
    middling_snap = replace(
        sample_snapshot, ticker="VEEV", market_cap_usd=32_800_000_000, revenue_growth_pct=16.1
    )
    return [
        (sample_instrument, sample_snapshot),
        (middling_inst, middling_snap),
        (weak, low_quality_snapshot),
    ]


def test_service_excludes_failing_candidates(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    result = ScreeningService().run(BUILTIN_SCREENS["quality_compounders"], diverse_universe)
    tickers = {c.instrument.ticker for c in result.candidates}
    assert "F" not in tickers
    assert "CDNS" in tickers


def test_service_sorts_by_score_descending(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    result = ScreeningService().run(BUILTIN_SCREENS["quality_compounders"], diverse_universe)
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)


def test_service_records_universe_size(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    result = ScreeningService().run(BUILTIN_SCREENS["quality_compounders"], diverse_universe)
    assert result.universe_size == len(diverse_universe)


def test_service_assigns_verdict(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    result = ScreeningService().run(BUILTIN_SCREENS["quality_compounders"], diverse_universe)
    assert all(isinstance(c.verdict, Verdict) for c in result.candidates)


def test_empty_universe_yields_zero_candidates() -> None:
    result = ScreeningService().run(BUILTIN_SCREENS["quality_compounders"], [])
    assert result.universe_size == 0
    assert result.filtered_count == 0


def test_ran_at_is_set() -> None:
    result = ScreeningService().run(BUILTIN_SCREENS["quality_compounders"], [])
    assert result.ran_at.tzinfo is not None
    assert result.ran_at.year >= 2026


def test_service_sector_filter_excludes_other_sectors(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    """When ``sectors`` is set, instruments outside that set are dropped."""
    from dataclasses import replace

    base = BUILTIN_SCREENS["all"]
    only_tech = replace(base, sectors=frozenset({"Technology"}))
    result = ScreeningService().run(only_tech, diverse_universe)
    # The diverse_universe fixture includes one Technology name (CDNS) plus
    # a non-Technology one — only the Technology row should survive.
    assert all(c.instrument.sector == "Technology" for c in result.candidates)
    assert len(result.candidates) >= 1


def test_service_sector_filter_none_means_pass_through(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    base = BUILTIN_SCREENS["all"]
    no_filter = ScreeningService().run(base, diverse_universe)
    assert no_filter.filtered_count == len(diverse_universe)


def test_service_verdict_filter_excludes_lower_verdicts(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    """When `verdicts` is set, candidates outside the set are dropped post-scoring."""
    from dataclasses import replace

    from openbourse.domain import Verdict

    base = BUILTIN_SCREENS["all"]
    only_strong = replace(base, verdicts=frozenset({Verdict.STRONG_INTEREST}))
    result = ScreeningService().run(only_strong, diverse_universe)
    assert all(c.verdict is Verdict.STRONG_INTEREST for c in result.candidates)


def test_service_verdict_filter_none_means_pass_through(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    """`verdicts=None` should match the unfiltered behavior."""
    base = BUILTIN_SCREENS["all"]
    no_filter = ScreeningService().run(base, diverse_universe)
    assert no_filter.filtered_count == len(diverse_universe)


def test_service_attaches_risk_score_to_each_candidate(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    """Every candidate the service emits should carry a 0-100 risk_score."""
    result = ScreeningService().run(BUILTIN_SCREENS["all"], diverse_universe)
    assert result.filtered_count >= 1
    for c in result.candidates:
        assert 0 <= c.risk_score <= 100


def test_service_max_risk_filter_drops_high_risk_rows(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    """A tight risk ceiling drops the levered low-quality row even if no
    other criterion would have rejected it."""
    base = BUILTIN_SCREENS["all"]  # no other thresholds
    conservative = replace(base, max_risk_score=40)
    result = ScreeningService().run(conservative, diverse_universe)
    tickers = {c.instrument.ticker for c in result.candidates}
    # Ford-like row carries the highest risk in the fixture; should be dropped.
    assert "F" not in tickers
    assert all(c.risk_score <= 40 for c in result.candidates)


def test_service_max_risk_filter_none_means_pass_through(
    diverse_universe: list[tuple[Instrument, FundamentalsSnapshot]],
) -> None:
    """``max_risk_score=None`` should leave the unfiltered universe intact."""
    base = BUILTIN_SCREENS["all"]
    no_filter = ScreeningService().run(base, diverse_universe)
    assert no_filter.filtered_count == len(diverse_universe)


def test_tie_break_is_alphabetical_by_ticker() -> None:
    snap = FundamentalsSnapshot(
        ticker="A",
        as_of=date(2026, 4, 30),
        market_cap_usd=10_000_000_000,
        revenue_growth_pct=20.0,
        gross_margin_pct=80.0,
        net_debt_to_ebitda=0.5,
        fcf_yield_pct=3.0,
    )
    universe = [
        (Instrument(ticker="ZZZ", name="Z Corp"), replace(snap, ticker="ZZZ")),
        (Instrument(ticker="AAA", name="A Corp"), replace(snap, ticker="AAA")),
    ]
    result = ScreeningService().run(BUILTIN_SCREENS["quality_compounders"], universe)
    assert [c.instrument.ticker for c in result.candidates] == ["AAA", "ZZZ"]
