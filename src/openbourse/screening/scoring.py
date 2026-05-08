"""Composite scoring and verdict thresholds.

The score combines five normalized components on the unit interval and
multiplies by 100 to yield an integer in ``[0, 100]``.

* ``growth``    — revenue growth %, capped at 30%.
* ``margin``    — gross margin %, capped at 100%.
* ``leverage``  — inverted net debt / EBITDA: 0.0x → 1.0, ≥3.0x → 0.0.
* ``fcf_yield`` — free-cash-flow yield %, capped at 8%.
* ``size``      — log market cap, $1B → 0.0, ≥$100B → 1.0.

Weights are tunable via the :class:`Weights` dataclass; defaults sum to 1.0.
All functions are pure and side-effect-free, which keeps them easy to test
and easy to call from the TUI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from openbourse.domain import FundamentalsSnapshot, Verdict

SCORE_MAX: Final = 100

VERDICT_THRESHOLDS: Final[dict[Verdict, int]] = {
    Verdict.STRONG_INTEREST: 90,
    Verdict.INTERESTING: 80,
    Verdict.PASS: 70,
}


@dataclass(frozen=True, slots=True)
class Weights:
    """Component weights for the composite score. Should sum to 1.0."""

    growth: float = 0.30
    margin: float = 0.25
    leverage: float = 0.15
    fcf_yield: float = 0.20
    size: float = 0.10

    def __post_init__(self) -> None:
        total = self.growth + self.margin + self.leverage + self.fcf_yield + self.size
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"weights must sum to 1.0, got {total!r}")


DEFAULT_WEIGHTS: Final = Weights()


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def normalize_growth(revenue_growth_pct: float) -> float:
    """Map revenue growth % to ``[0, 1]``. Caps at 30%."""
    return _clip(revenue_growth_pct / 30.0)


def normalize_margin(gross_margin_pct: float) -> float:
    """Map gross margin % to ``[0, 1]``."""
    return _clip(gross_margin_pct / 100.0)


def normalize_leverage(net_debt_to_ebitda: float) -> float:
    """Lower leverage scores higher. ``0.0x → 1.0``, ``≥3.0x → 0.0``."""
    return _clip(1.0 - net_debt_to_ebitda / 3.0)


def normalize_fcf_yield(fcf_yield_pct: float) -> float:
    """Map FCF yield % to ``[0, 1]``. Caps at 8%."""
    return _clip(fcf_yield_pct / 8.0)


def normalize_size(market_cap_usd: float) -> float:
    """Log-scaled market cap. ``$1B → 0.0``, ``≥$100B → 1.0``."""
    if market_cap_usd <= 1_000_000_000:
        return 0.0
    cap_b = market_cap_usd / 1_000_000_000
    return _clip(math.log10(cap_b) / 2.0)


def composite_score(snapshot: FundamentalsSnapshot, *, weights: Weights = DEFAULT_WEIGHTS) -> int:
    """Return an integer 0-100 composite score for ``snapshot``."""
    components = (
        normalize_growth(snapshot.revenue_growth_pct) * weights.growth
        + normalize_margin(snapshot.gross_margin_pct) * weights.margin
        + normalize_leverage(snapshot.net_debt_to_ebitda) * weights.leverage
        + normalize_fcf_yield(snapshot.fcf_yield_pct) * weights.fcf_yield
        + normalize_size(snapshot.market_cap_usd) * weights.size
    )
    return round(components * SCORE_MAX)


def verdict_for(score: int) -> Verdict:
    """Map an integer score onto a :class:`Verdict`.

    Scores at or above the ``STRONG_INTEREST`` threshold map to that verdict;
    falling thresholds drop into ``INTERESTING``, ``PASS``, then ``REJECT``.
    """
    if score >= VERDICT_THRESHOLDS[Verdict.STRONG_INTEREST]:
        return Verdict.STRONG_INTEREST
    if score >= VERDICT_THRESHOLDS[Verdict.INTERESTING]:
        return Verdict.INTERESTING
    if score >= VERDICT_THRESHOLDS[Verdict.PASS]:
        return Verdict.PASS
    return Verdict.REJECT
