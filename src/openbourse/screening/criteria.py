"""Screen definitions and pure-function criteria evaluation."""

from __future__ import annotations

from openbourse.domain import FundamentalsSnapshot, ScreenDefinition

# A practically-infinite bound for the unfiltered "all" screen. Float values
# rather than ``inf`` so they round-trip through JSON cleanly when persisted.
_PERMISSIVE_LOWER = -1e15
_PERMISSIVE_UPPER = 1e15


BUILTIN_SCREENS: dict[str, ScreenDefinition] = {
    "all": ScreenDefinition(
        name="all",
        description=(
            "All instruments — no filters; sorts the entire ingested universe by "
            "composite score. Use this to browse small caps, deteriorating names, "
            "and outliers that other screens hide."
        ),
        min_revenue_growth_pct=_PERMISSIVE_LOWER,
        min_gross_margin_pct=_PERMISSIVE_LOWER,
        max_net_debt_to_ebitda=_PERMISSIVE_UPPER,
        min_market_cap_usd=0.0,
        min_fcf_yield_pct=_PERMISSIVE_LOWER,
    ),
    "quality_compounders": ScreenDefinition(
        name="quality_compounders",
        description=(
            "Quality Compounders — rev growth ≥15%, gross margin ≥40%, "
            "net debt/EBITDA ≤1.0, mkt cap ≥$1B"
        ),
        min_revenue_growth_pct=15.0,
        min_gross_margin_pct=40.0,
        max_net_debt_to_ebitda=1.0,
        min_market_cap_usd=1_000_000_000,
    ),
    "deep_value": ScreenDefinition(
        name="deep_value",
        description=("Deep Value — FCF yield ≥6%, net debt/EBITDA ≤2.0, mkt cap ≥$500M"),
        min_fcf_yield_pct=6.0,
        max_net_debt_to_ebitda=2.0,
        min_market_cap_usd=500_000_000,
    ),
    "high_growth": ScreenDefinition(
        name="high_growth",
        description=("High Growth — rev growth ≥25%, gross margin ≥60%, mkt cap ≥$1B"),
        min_revenue_growth_pct=25.0,
        min_gross_margin_pct=60.0,
        min_market_cap_usd=1_000_000_000,
    ),
}


def passes_screen(snapshot: FundamentalsSnapshot, screen: ScreenDefinition) -> bool:
    """Return True iff ``snapshot`` satisfies every threshold in ``screen``."""
    return (
        snapshot.revenue_growth_pct >= screen.min_revenue_growth_pct
        and snapshot.gross_margin_pct >= screen.min_gross_margin_pct
        and snapshot.net_debt_to_ebitda <= screen.max_net_debt_to_ebitda
        and snapshot.market_cap_usd >= screen.min_market_cap_usd
        and snapshot.fcf_yield_pct >= screen.min_fcf_yield_pct
    )
