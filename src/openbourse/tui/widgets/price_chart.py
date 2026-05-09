"""Price-over-time chart widget.

A single full-width plotext line chart. Distinguished from
:mod:`openbourse.tui.widgets.history_charts` (which renders four small
fundamental-trend sparklines in a 2x2 grid): this widget renders one
high-resolution price series per call, typically 3 years of daily closes.

The line is coloured by net direction over the displayed window —
green if the closing price ends higher than it started, red if lower.
"""

from __future__ import annotations

from datetime import date

import plotext as plt  # type: ignore[import-untyped]
from rich.text import Text
from textual.widgets import Static


class PriceChart(Static):
    """Single-line close-price chart over an arbitrary date range."""

    DEFAULT_CSS = """
    PriceChart {
        height: 14;
        width: 1fr;
        padding: 0 1;
    }
    """

    CHART_HEIGHT = 11

    def __init__(
        self,
        ticker: str,
        points: list[tuple[date, float]],
        *,
        chart_width: int = 140,
    ) -> None:
        super().__init__()
        self._ticker = ticker
        self._points = points
        self._chart_width = chart_width

    def render(self) -> Text:
        """Render the chart on every repaint (cheap; plotext is fast)."""
        if len(self._points) < 2:
            return Text(
                f"{self._ticker} — insufficient price history "
                f"(need ≥2 closes, got {len(self._points)})",
                style="dim",
            )
        return self._render_chart()

    def _render_chart(self) -> Text:
        """Build the actual plotext output as Rich-renderable ANSI."""
        dates = [p[0] for p in self._points]
        prices = [p[1] for p in self._points]
        x = list(range(len(prices)))

        # Direction-coloured line: green when the period ended higher,
        # red when lower. Read at a glance.
        direction_color = "green" if prices[-1] >= prices[0] else "red"

        plt.clear_figure()
        plt.theme("dark")
        change_pct = ((prices[-1] / prices[0]) - 1) * 100 if prices[0] else 0.0
        plt.title(
            f"{self._ticker}  close ${prices[-1]:,.2f}  "
            f"({change_pct:+.1f}% over {dates[0]} → {dates[-1]})"
        )
        plt.plot(x, prices, marker="braille", color=direction_color)

        # Sample 5 evenly-spaced x-axis labels from the date series so the
        # axis is readable without overcrowding.
        if len(dates) >= 5:
            tick_indices = [
                0,
                len(dates) // 4,
                len(dates) // 2,
                3 * len(dates) // 4,
                len(dates) - 1,
            ]
            plt.xticks(
                tick_indices,
                [dates[i].strftime("%Y-%m") for i in tick_indices],
            )

        plt.plotsize(self._chart_width, self.CHART_HEIGHT)
        return Text.from_ansi(str(plt.build()))
