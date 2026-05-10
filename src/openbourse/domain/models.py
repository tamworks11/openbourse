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
    # Return on invested capital, in percent. 0.0 when the underlying
    # provider can't produce one (statements missing tax info, balance-
    # sheet items, etc.) — the chart treats 0 as "no data" by skipping
    # the point rather than rendering a flat line at zero.
    roic_pct: float = 0.0


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
    # Risk-tolerance ceiling. Candidates with computed risk_score above
    # this value are filtered out. ``None`` disables the filter entirely.
    # Bands: ≤30 low risk, 30-60 moderate, ≥60 high.
    max_risk_score: int | None = None
    sectors: frozenset[str] | None = None
    verdicts: frozenset[Verdict] | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    """An instrument that passed a screen, with its score, risk, and verdict.

    ``score`` is the composite quality score (0-100, higher better);
    ``risk_score`` is the parallel vulnerability score (0-100, higher
    riskier). Both are computed by the screening service from the
    snapshot. They are independent — a high-quality business can still
    register meaningful risk (e.g., small market cap).
    """

    instrument: Instrument
    snapshot: FundamentalsSnapshot
    score: int
    verdict: Verdict
    risk_score: int = 0


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
class ValuationBand:
    """One valuation multiple's current value plus N-year history.

    Lives next to :class:`FundamentalsSnapshot` because both describe a
    single instrument at a point in time, but valuation is a separate
    concept: it composes price *and* fundamentals, so it changes whenever
    either side changes — far more often than the underlying snapshot.

    ``history`` is ascending by date. Empty history means we couldn't
    construct one (e.g., insufficient back-statements on the free tier);
    the band will still render with the current value but no comparison.
    """

    label: str  # human-readable: "P/E", "EV/EBITDA", "EV/Revenue", "P/FCF"
    current: float | None
    history: tuple[tuple[date, float], ...] = ()

    @property
    def has_history(self) -> bool:
        """True iff there are at least two historical points to band from."""
        return len(self.history) >= 2

    @property
    def low(self) -> float | None:
        """Minimum value across the historical series. ``None`` if empty."""
        if not self.history:
            return None
        return min(v for _, v in self.history)

    @property
    def high(self) -> float | None:
        """Maximum value across the historical series. ``None`` if empty."""
        if not self.history:
            return None
        return max(v for _, v in self.history)

    @property
    def median(self) -> float | None:
        """Median value across the historical series. ``None`` if empty.

        Linear interpolation when the count is even — just the average of
        the two centre values, which is the standard convention.
        """
        if not self.history:
            return None
        vals = sorted(v for _, v in self.history)
        n = len(vals)
        if n % 2 == 1:
            return vals[n // 2]
        return (vals[n // 2 - 1] + vals[n // 2]) / 2

    def percentile_rank(self) -> float | None:
        """Where ``current`` sits in the historical distribution, 0-100.

        0 means at-or-below the all-time low, 100 means at-or-above the
        all-time high, 50 means exactly at the median. Returns ``None``
        when there's no current value or no history. Range collapses
        (every historical value identical) return 50 by convention so
        the visual band still shows something.
        """
        if self.current is None or not self.history:
            return None
        low = self.low
        high = self.high
        if low is None or high is None:
            return None
        if high == low:
            return 50.0
        ratio = (self.current - low) / (high - low)
        return max(0.0, min(100.0, ratio * 100))


@dataclass(frozen=True, slots=True)
class ValuationSnapshot:
    """Composite valuation read for a single ticker.

    Contains one :class:`ValuationBand` per multiple we track. The TUI
    iterates the bands tuple in order to render the panel — providers
    should keep a stable ordering across calls so the UI doesn't reshuffle.
    """

    ticker: str
    as_of: date
    bands: tuple[ValuationBand, ...] = ()


@dataclass(frozen=True, slots=True)
class Quote:
    """Latest price quote for a ticker.

    Returned by :class:`~openbourse.providers.base.QuoteProvider`.
    Distinct from :class:`FundamentalsSnapshot` — quotes refresh on the
    seconds-to-minutes timescale; snapshots refresh on the
    weeks-to-quarters timescale. Keeping them separate lets the UI tick
    the price column without re-running the (expensive) snapshot
    pipeline.
    """

    ticker: str
    price_usd: float
    fetched_at: datetime
    volume: int | None = None


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
