"""History charts widget — 2x2 grid of plotext sparklines.

Renders quarterly trajectories of the four headline metrics so the analyst
can answer "is this getting better or worse?" at a glance.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import plotext as plt  # type: ignore[import-untyped]
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Static

from openbourse.domain import FundamentalsSnapshot

ChartGetter = Callable[[FundamentalsSnapshot], float]

CHART_DEFS: tuple[tuple[str, ChartGetter, str], ...] = (
    ("Revenue growth %", lambda s: s.revenue_growth_pct, "green"),
    ("Gross margin %", lambda s: s.gross_margin_pct, "cyan"),
    ("FCF yield %", lambda s: s.fcf_yield_pct, "yellow"),
    ("Net debt / EBITDA", lambda s: s.net_debt_to_ebitda, "magenta"),
)


def _render_chart(
    title: str,
    snapshots: list[FundamentalsSnapshot],
    getter: ChartGetter,
    color: str,
    *,
    width: int,
    height: int,
) -> str:
    """Build a single plotext chart for ``snapshots`` as an ANSI string.

    Returns a placeholder message when there aren't enough data points to
    plot a line (need at least two).
    """
    if len(snapshots) < 2:
        return f"{title}\n  insufficient history (need ≥2 snapshots)"

    plt.clear_figure()
    plt.theme("dark")
    plt.title(title)
    x = list(range(len(snapshots)))
    y = [getter(s) for s in snapshots]
    plt.plot(x, y, color=color, marker="braille")

    # Date labels on the x-axis: show first, mid, and last only — full dates
    # at every tick make the small charts unreadable.
    if len(snapshots) >= 3:
        ticks = [0, len(snapshots) // 2, len(snapshots) - 1]
        labels = [snapshots[i].as_of.strftime("%y-%m") for i in ticks]
        plt.xticks(ticks, labels)

    plt.plotsize(width, height)
    return str(plt.build())


class HistoryCharts(Grid):
    """2x2 grid of small plotext line charts driven by a list of snapshots."""

    DEFAULT_CSS = """
    HistoryCharts {
        grid-size: 2 2;
        grid-gutter: 0;
        height: 22;
    }

    HistoryCharts > Static {
        height: 100%;
        width: 100%;
        padding: 0 1;
    }
    """

    # Width per cell in the 2x2 grid. Sized for the brief screen's left
    # column (~half a 140-col terminal): 35 fits two side-by-side charts
    # in ~70 columns with a small gutter.
    CHART_WIDTH: ClassVar[int] = 35
    CHART_HEIGHT: ClassVar[int] = 10

    def __init__(self, snapshots: list[FundamentalsSnapshot]) -> None:
        super().__init__()
        self._snapshots = snapshots

    def compose(self) -> ComposeResult:
        """Yield one Static per chart in the order defined by ``CHART_DEFS``."""
        for title, getter, color in CHART_DEFS:
            chart_str = _render_chart(
                title,
                self._snapshots,
                getter,
                color,
                width=self.CHART_WIDTH,
                height=self.CHART_HEIGHT,
            )
            yield Static(Text.from_ansi(chart_str))
