"""Domain dataclasses shared across all layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class Verdict(StrEnum):
    """Final categorical assessment for a candidate.

    Order is monotone in interest: ``REJECT`` < ``PASS`` < ``INTERESTING`` <
    ``STRONG_INTEREST``. Rules that map a numeric score to a verdict live in
    :mod:`openbourse.screening.scoring`.
    """

    REJECT = "REJECT"
    PASS = "PASS"
    INTERESTING = "INTERESTING"
    STRONG_INTEREST = "STRONG_INTEREST"


@dataclass(frozen=True, slots=True)
class Instrument:
    """A publicly traded equity."""

    ticker: str
    name: str
    sector: str | None = None
    exchange: str | None = None
    cik: str | None = None  # SEC central index key, when available


@dataclass(frozen=True, slots=True)
class FundamentalsSnapshot:
    """Point-in-time fundamentals for an instrument.

    All ratios are expressed as percentages (e.g. ``18.4`` means 18.4%) unless
    explicitly noted. Currency amounts are in USD.
    """

    ticker: str
    as_of: date
    market_cap_usd: float
    revenue_growth_pct: float
    gross_margin_pct: float
    net_debt_to_ebitda: float
    fcf_yield_pct: float
    revenue_ttm_usd: float | None = None
    ebitda_ttm_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ScreenDefinition:
    """A named, declarative filter over the universe of instruments."""

    name: str
    description: str
    min_revenue_growth_pct: float = 0.0
    min_gross_margin_pct: float = 0.0
    max_net_debt_to_ebitda: float = float("inf")
    min_market_cap_usd: float = 0.0
    min_fcf_yield_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class Candidate:
    """An instrument that passed a screen, with its score and verdict."""

    instrument: Instrument
    snapshot: FundamentalsSnapshot
    score: int
    verdict: Verdict


@dataclass(frozen=True, slots=True)
class ScreenResult:
    """Output of running one screen against the universe."""

    screen: ScreenDefinition
    ran_at: datetime
    universe_size: int
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)

    @property
    def filtered_count(self) -> int:
        return len(self.candidates)


@dataclass(frozen=True, slots=True)
class AiBrief:
    """An AI-generated qualitative brief for an instrument."""

    ticker: str
    generated_at: datetime
    model: str
    summary: str
    bullets: tuple[str, ...] = field(default_factory=tuple)
    raw: dict[str, Any] = field(default_factory=dict)
