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
    business_summary: str | None = None  # 1-2 paragraph description of the business


@dataclass(frozen=True, slots=True)
class FundamentalsSnapshot:
    """Point-in-time fundamentals for an instrument.

    All ratios are expressed as percentages (e.g. ``18.4`` means 18.4%) unless
    explicitly noted. Currency amounts are in USD.

    ``price_usd`` is the close price as of ``as_of`` when the underlying
    provider exposes one. It is optional because not every data source
    returns a price for historical fundamentals snapshots.
    """

    ticker: str
    as_of: date
    market_cap_usd: float
    revenue_growth_pct: float
    gross_margin_pct: float
    net_debt_to_ebitda: float
    fcf_yield_pct: float
    price_usd: float | None = None
    revenue_ttm_usd: float | None = None
    ebitda_ttm_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ScreenDefinition:
    """A named, declarative filter over the universe of instruments.

    Each numeric threshold is optional: ``None`` disables that criterion
    (the screen ignores it when filtering). This lets a user toggle
    individual filters on and off in the TUI without inventing sentinel
    values like ``inf``.

    ``verdicts`` is a separate post-scoring filter: when set, only candidates
    whose computed verdict is in the given set survive. ``None`` disables
    the verdict filter entirely (every verdict passes).
    """

    name: str
    description: str
    min_revenue_growth_pct: float | None = None
    min_gross_margin_pct: float | None = None
    max_net_debt_to_ebitda: float | None = None
    min_market_cap_usd: float | None = None
    min_fcf_yield_pct: float | None = None
    sectors: frozenset[str] | None = None
    verdicts: frozenset[Verdict] | None = None


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
        """Number of instruments that survived the screen's filter."""
        return len(self.candidates)


@dataclass(frozen=True, slots=True)
class ConcernFinding:
    """One row of "user-defined concern checked against this candidate".

    ``status`` is one of:

    * ``"flagged"`` — there's evidence the concern applies.
    * ``"clear"``   — there's evidence it doesn't apply.
    * ``"unknown"`` — no evidence either way (default for new concerns).
    """

    concern: str
    status: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class AiBrief:
    """An AI-generated qualitative brief for an instrument.

    The shape is deliberately opinionated: a one-line summary, then three
    parallel sections (bull / bear / risks) so the LLM can't fudge the
    bear case by burying it in the summary, plus a list of concern-level
    findings the user has explicitly asked about.
    """

    ticker: str
    generated_at: datetime
    model: str
    summary: str
    bull: tuple[str, ...] = field(default_factory=tuple)
    bear: tuple[str, ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)
    concerns: tuple[ConcernFinding, ...] = field(default_factory=tuple)
    raw: dict[str, Any] = field(default_factory=dict)
