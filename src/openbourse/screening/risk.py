"""Risk score: pure-function 0-100 metric where higher = riskier.

The mirror of :mod:`openbourse.screening.scoring`. The composite score
asks "how good is this business?"; the risk score asks "how vulnerable
is this business to a bad outcome?". Same inputs, different lens.

A candidate can carry a high composite AND a high risk simultaneously:
a small, fast-growing software company with thin FCF can score 90 on
quality (great margins, minimal leverage, growing fast) but still
register 60+ on risk (small cap, low FCF cushion). Surfacing both lets
the user filter "show me high-quality names that fit my risk budget".

Bands:

* **0-30 (low risk)**   — large-cap, low leverage, high margin, real FCF.
* **30-60 (moderate)**  — typical compounder territory.
* **60-100 (high)**     — small-cap, levered, thin margins, weak FCF.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from openbourse.domain import FundamentalsSnapshot

RISK_MAX: int = 100


@dataclass(frozen=True, slots=True)
class RiskWeights:
    """Weights for the per-component risk contributions.

    Must sum to 1.0. Defaults emphasize leverage as the primary risk
    signal, with size and margin as secondary, then FCF yield. Adjust
    here (not at the call site) so all callers see consistent behaviour.
    """

    leverage: float = 0.35
    size: float = 0.25
    margin: float = 0.20
    fcf_yield: float = 0.20

    def __post_init__(self) -> None:
        """Reject configurations that don't sum to 1.0."""
        total = self.leverage + self.size + self.margin + self.fcf_yield
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"weights must sum to 1.0, got {total}")


DEFAULT_WEIGHTS = RiskWeights()


def normalize_leverage_risk(leverage: float) -> float:
    """Map net debt / EBITDA to a 0-1 risk contribution.

    Negative leverage (net cash) → 0. Threshold of 5x is the saturation
    point — anything beyond is already maximum-risk, so capping there
    prevents one extreme value from drowning out the other components.
    """
    return min(max(leverage / 5.0, 0.0), 1.0)


def normalize_size_risk(market_cap_usd: float) -> float:
    """Map market cap to a 0-1 risk contribution on a log scale.

    Anchors: $1B → 1.0 (max small-cap risk), $100B+ → 0.0 (mega-cap, low
    size risk). Below $1B saturates at 1.0; above $100B saturates at 0.
    Log-scale because size risk doesn't scale linearly — the gap between
    $1B and $10B matters far more than between $90B and $100B.
    """
    if market_cap_usd <= 1_000_000_000:
        return 1.0
    if market_cap_usd >= 100_000_000_000:
        return 0.0
    # log10(1e9)=9, log10(1e11)=11. Linear interpolate on the log span.
    return (11.0 - math.log10(market_cap_usd)) / 2.0


def normalize_margin_risk(gross_margin_pct: float) -> float:
    """Map gross margin to a 0-1 risk contribution.

    Inverse-linear: 0% margin → 1.0 (no pricing power, full risk), 100% →
    0.0 (software-like margins, minimal pricing risk). Clamps below 0
    and above 100 to keep weird inputs from blowing up the composite.
    """
    return max(0.0, min(1.0, 1.0 - (gross_margin_pct / 100.0)))


def normalize_fcf_risk(fcf_yield_pct: float) -> float:
    """Map FCF yield to a 0-1 risk contribution.

    8%+ FCF yield = 0 risk contribution; 0% = 1.0. The 8% threshold lines
    up with the corresponding "ideal" used in the style-fit module.
    Negative FCF yield (cash-burning company) saturates at 1.0.
    """
    return max(0.0, min(1.0, 1.0 - (fcf_yield_pct / 8.0)))


def compute_risk_score(
    snapshot: FundamentalsSnapshot,
    weights: RiskWeights = DEFAULT_WEIGHTS,
) -> int:
    """Return a 0-100 integer risk score for ``snapshot``. Higher = riskier.

    The score is a weighted average of four normalized risk components,
    rounded to the nearest integer. Pure function — same input always
    produces the same output, so it's safe to cache or memoize on the
    snapshot tuple.
    """
    composite = (
        weights.leverage * normalize_leverage_risk(snapshot.net_debt_to_ebitda)
        + weights.size * normalize_size_risk(snapshot.market_cap_usd)
        + weights.margin * normalize_margin_risk(snapshot.gross_margin_pct)
        + weights.fcf_yield * normalize_fcf_risk(snapshot.fcf_yield_pct)
    )
    return round(composite * RISK_MAX)
