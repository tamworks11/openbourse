"""ROIC trend chart — single full-width plotext line.

Return on Invested Capital is the headline quality metric for compounders:
trending upward means the business is generating more profit per dollar
of capital deployed, which compounds wealth. Pulled out of the existing
2x2 fundamentals grid as a separate, prominent chart because:

* It reads better at full width (more historical points fit cleanly).
* It deserves visual emphasis given how much it drives the buy decision.
* The 2x2 grid stays a 2x2 — adding a 5th cell would have left an
  awkward empty slot or required a full layout reshuffle.
"""

from __future__ import annotations

from typing import ClassVar

import plotext as plt  # type: ignore[import-untyped]
from rich.text import Text
from textual.widgets import Static

from openbourse.domain import FundamentalsSnapshot


class RoicChart(Static):
    """Single full-width plotext chart of annual ROIC over time."""

    DEFAULT_CSS = """
    RoicChart {
        height: 14;
        width: 1fr;
        padding: 0 1;
    }
    """

    CHART_HEIGHT: ClassVar[int] = 11

    def __init__(
        self,
        snapshots: list[FundamentalsSnapshot],
        *,
        chart_width: int = 70,
    ) -> None:
        super().__init__()
        # Drop snapshots whose ROIC is the placeholder 0.0 — providers
        # produce 0 when the inputs are missing, which would render as
        # noise in the trend line. The chart's "insufficient" fallback
        # kicks in when fewer than 2 valid points remain.
        self._snapshots = [s for s in snapshots if s.roic_pct > 0]
        self._chart_width = chart_width

    def render(self) -> Text:
        """Build the plotext chart on every repaint."""
        if len(self._snapshots) < 2:
            return Text(
                "ROIC %\n  insufficient history (need ≥2 annual snapshots with ROIC computed)",
                style="dim",
            )
        return self._render_chart()

    def _render_chart(self) -> Text:
        """Render annual ROIC as a single line, current value in the title."""
        snaps = self._snapshots
        x = list(range(len(snaps)))
        y = [s.roic_pct for s in snaps]

        plt.clear_figure()
        plt.theme("dark")
        latest = y[-1]
        first = y[0]
        change_pp = latest - first  # percentage-point change
        plt.title(
            f"ROIC %  current {latest:.1f}%  "
            f"({change_pp:+.1f}pp over {snaps[0].as_of} → {snaps[-1].as_of})"
        )
        # White is intentional — the four small charts already use the
        # green/cyan/yellow/magenta palette; ROIC gets its own accent so
        # users know it's a separately-prominent metric.
        plt.plot(x, y, marker="braille", color="white")

        # Show first / mid / last x-tick — fewer than the price chart
        # since the data points are typically 5-7 not 750.
        if len(snaps) >= 3:
            ticks = [0, len(snaps) // 2, len(snaps) - 1]
            labels = [snaps[i].as_of.strftime("%Y") for i in ticks]
            plt.xticks(ticks, labels)

        plt.plotsize(self._chart_width, self.CHART_HEIGHT)
        return Text.from_ansi(str(plt.build()))
