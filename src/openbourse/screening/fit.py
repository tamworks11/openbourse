"""Style-fit score: how closely a candidate matches a screen's enabled criteria.

Distinct from ``composite_score`` (the universal quality score in
:mod:`openbourse.screening.scoring`):

* **Composite score** answers "is this a good business?" against fixed
  weights — the same inputs always produce the same score.
* **Style-fit score** answers "does this candidate look like what the
  active screen is asking for?" — re-computed against the user's filter
  thresholds, so the same business reads differently under different
  screens.

Both are visible on the brief screen so the user can spot disagreements
(e.g., a name with a high composite but low style-fit is "good but not
what this screen targets").

The math is intentionally transparent: per enabled criterion we map the
candidate's metric onto a piecewise-linear curve where the threshold
itself is the 50% inflection. Average across criteria.
"""

from __future__ import annotations

from openbourse.domain import FundamentalsSnapshot, ScreenDefinition


def compute_style_fit(snapshot: FundamentalsSnapshot, screen: ScreenDefinition) -> float:
    """Return a 0-100 score for how well ``snapshot`` matches ``screen``.

    100 — comfortably exceeds every enabled threshold.
    50  — exactly meets every enabled threshold.
    0   — fails every enabled criterion badly.

    A screen with no enabled numeric criteria gets 100 (nothing to fail).
    Disabled criteria don't contribute. The verdict / sector filters
    aren't part of the fit math — they're hard yes/no gates handled at
    the service level.
    """
    parts: list[float] = []

    if screen.min_revenue_growth_pct is not None:
        parts.append(
            _fit_min(
                snapshot.revenue_growth_pct,
                threshold=screen.min_revenue_growth_pct,
                soft_ceiling=max(screen.min_revenue_growth_pct * 2.0, 30.0),
            )
        )
    if screen.min_gross_margin_pct is not None:
        parts.append(
            _fit_min(
                snapshot.gross_margin_pct,
                threshold=screen.min_gross_margin_pct,
                soft_ceiling=min(screen.min_gross_margin_pct * 1.5, 95.0),
            )
        )
    if screen.max_net_debt_to_ebitda is not None:
        parts.append(
            _fit_max(
                snapshot.net_debt_to_ebitda,
                threshold=screen.max_net_debt_to_ebitda,
                soft_floor=0.0,
            )
        )
    if screen.min_market_cap_usd is not None:
        # Log-scale fit: doubling above the threshold continues to add value.
        parts.append(
            _fit_min(
                snapshot.market_cap_usd,
                threshold=screen.min_market_cap_usd,
                soft_ceiling=max(screen.min_market_cap_usd * 50.0, 100e9),
            )
        )
    if screen.min_fcf_yield_pct is not None:
        parts.append(
            _fit_min(
                snapshot.fcf_yield_pct,
                threshold=screen.min_fcf_yield_pct,
                soft_ceiling=max(screen.min_fcf_yield_pct * 2.0, 5.0),
            )
        )

    if not parts:
        return 100.0
    return sum(parts) / len(parts)


def _fit_min(value: float, *, threshold: float, soft_ceiling: float) -> float:
    """Score "value should be ≥ threshold; ideal at ``soft_ceiling``".

    Piecewise-linear:
    * ``value ≤ 0``         → 0
    * ``value == threshold``→ 50
    * ``value ≥ soft_ceiling`` → 100
    * Linear interpolation between those anchors.
    """
    if value <= 0:
        return 0.0
    if soft_ceiling <= threshold:
        # Degenerate band; treat any value ≥ threshold as full credit.
        return 100.0 if value >= threshold else 50.0 * (value / threshold)
    if value >= soft_ceiling:
        return 100.0
    if value <= threshold:
        return 50.0 * (value / threshold)
    return 50.0 + 50.0 * (value - threshold) / (soft_ceiling - threshold)


def _fit_max(value: float, *, threshold: float, soft_floor: float) -> float:
    """Score "value should be ≤ threshold; ideal at ``soft_floor``".

    Mirror of :func:`_fit_min` for "max" constraints (e.g., leverage):
    a value of 0x debt is best, threshold equals 50% fit, anything beyond
    ``2 * threshold`` is fully out of band.
    """
    soft_ceiling = threshold * 2 if threshold > 0 else 1.0
    if value <= soft_floor:
        return 100.0
    if value >= soft_ceiling:
        return 0.0
    if value <= threshold:
        # 100 → 50 across [soft_floor, threshold]
        span = threshold - soft_floor
        return 100.0 if span <= 0 else 100.0 - 50.0 * (value - soft_floor) / span
    # 50 → 0 across (threshold, soft_ceiling]
    span = soft_ceiling - threshold
    return 50.0 - 50.0 * (value - threshold) / span if span > 0 else 50.0
