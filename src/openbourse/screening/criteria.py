"""Screen definitions and pure-function criteria evaluation."""

from __future__ import annotations

from openbourse.domain import FundamentalsSnapshot, ScreenDefinition

# Built-in screens use *short* descriptions — just the screen's intent.
# The actual filter thresholds are formatted dynamically by
# :func:`format_active_filters` so the screener UI reflects edits made
# via the filter modal rather than this static string.
BUILTIN_SCREENS: dict[str, ScreenDefinition] = {
    "all": ScreenDefinition(
        name="all",
        description="All instruments — sorts the universe by composite score",
        # Every threshold left as None: passes_screen short-circuits to True.
    ),
    "quality_compounders": ScreenDefinition(
        name="quality_compounders",
        description="Quality Compounders — durable, capital-efficient growth",
        min_revenue_growth_pct=15.0,
        min_gross_margin_pct=40.0,
        max_net_debt_to_ebitda=1.0,
        min_market_cap_usd=1_000_000_000,
        min_fcf_yield_pct=0.0,
    ),
    "deep_value": ScreenDefinition(
        name="deep_value",
        description="Deep Value — cheap with manageable leverage",
        min_fcf_yield_pct=6.0,
        max_net_debt_to_ebitda=2.0,
        min_market_cap_usd=500_000_000,
    ),
    "high_growth": ScreenDefinition(
        name="high_growth",
        description="High Growth — fast-growing premium businesses",
        min_revenue_growth_pct=25.0,
        min_gross_margin_pct=60.0,
        min_market_cap_usd=1_000_000_000,
    ),
}


def format_active_filters(screen: ScreenDefinition) -> str:
    """Render the screen's enabled thresholds as a compact, human-readable line.

    Returns ``"no filters"`` when every threshold is ``None``. Used by both
    the TUI screen-meta line and ``bourse screen list`` so the displayed
    criteria always match what's actually being applied.
    """
    parts: list[str] = []
    if screen.min_revenue_growth_pct is not None:
        parts.append(f"rev growth ≥{screen.min_revenue_growth_pct:g}%")
    if screen.min_gross_margin_pct is not None:
        parts.append(f"gross margin ≥{screen.min_gross_margin_pct:g}%")
    if screen.max_net_debt_to_ebitda is not None:
        parts.append(f"net debt/EBITDA ≤{screen.max_net_debt_to_ebitda:g}x")
    if screen.min_market_cap_usd is not None:
        cap = screen.min_market_cap_usd
        if cap >= 1e9:
            parts.append(f"mkt cap ≥${cap / 1e9:g}B")
        elif cap >= 1e6:
            parts.append(f"mkt cap ≥${cap / 1e6:g}M")
        else:
            parts.append(f"mkt cap ≥${cap:g}")
    if screen.min_fcf_yield_pct is not None:
        parts.append(f"FCF yield ≥{screen.min_fcf_yield_pct:g}%")
    if screen.sectors is not None:
        # Alphabetical so "Healthcare, Technology" reads predictably regardless
        # of set-iteration order.
        parts.append("sector ∈ {" + ", ".join(sorted(screen.sectors)) + "}")
    if screen.verdicts is not None:
        # Render highest-interest verdicts first (STRONG_INTEREST → REJECT) so
        # the filter line reads naturally regardless of set-iteration order.
        from openbourse.domain import Verdict

        ordered = [v.value for v in reversed(list(Verdict)) if v in screen.verdicts]
        parts.append("verdict ∈ {" + ", ".join(ordered) + "}")

    return " · ".join(parts) if parts else "no filters"


def passes_screen(snapshot: FundamentalsSnapshot, screen: ScreenDefinition) -> bool:
    """Return True iff ``snapshot`` satisfies every *enabled* threshold in ``screen``.

    A ``None`` threshold means the criterion is disabled, so it always
    passes. This makes turning filters on/off in the editor a one-bit
    change rather than reaching for sentinel values like ``±inf``.
    """
    if (
        screen.min_revenue_growth_pct is not None
        and snapshot.revenue_growth_pct < screen.min_revenue_growth_pct
    ):
        return False
    if (
        screen.min_gross_margin_pct is not None
        and snapshot.gross_margin_pct < screen.min_gross_margin_pct
    ):
        return False
    if (
        screen.max_net_debt_to_ebitda is not None
        and snapshot.net_debt_to_ebitda > screen.max_net_debt_to_ebitda
    ):
        return False
    if (
        screen.min_market_cap_usd is not None
        and snapshot.market_cap_usd < screen.min_market_cap_usd
    ):
        return False
    return not (
        screen.min_fcf_yield_pct is not None and snapshot.fcf_yield_pct < screen.min_fcf_yield_pct
    )
