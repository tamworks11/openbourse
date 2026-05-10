"""Valuation panel — current multiples plus a percentile-rank band per metric.

Renders a compact table on the brief screen:

    Valuation
    ─────────
    P/E         24.5x  bar...  35  (18.2 - 42.1, med 26.4)
    EV/EBITDA   18.2x  bar...  21  (14.5 - 28.0, med 19.8)
    EV/Revenue   8.4x  bar...  82  (3.2  - 10.5, med 6.9)
    P/FCF       32.1x  bar...  55  (18.0 - 48.0, med 28.0)

Bar colour encodes whether the current value is cheap (green, <30th pct),
fair (yellow, 30-70), or expensive (red, >=70). When a metric has no
history (free-tier FMP, missing data), the row collapses to current
value only.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from openbourse.domain import ValuationBand, ValuationSnapshot

BAR_LENGTH = 14  # characters in the percentile bar
FILLED_GLYPH = "▮"
EMPTY_GLYPH = "▯"


def _band_color(percentile: float | None) -> str:
    """Map a 0-100 percentile to the band colour for the bar.

    Cheap (≤30) is green, fair (30-70) yellow, expensive (≥70) red.
    Same band thresholds as the risk-score column on the screener so
    the visual language stays consistent across screens. ``None`` (no
    historical data) renders dim grey.
    """
    if percentile is None:
        return "dim"
    if percentile <= 30:
        return "green"
    if percentile < 70:
        return "yellow"
    return "red"


def _format_multiple(value: float | None) -> str:
    """Render a multiple as ``24.5x``, two-decimal precision; em-dash if missing."""
    if value is None:
        return "—"
    return f"{value:.1f}x"


def _format_band_row(band: ValuationBand) -> str:
    """Build the Rich-marked-up row text for one valuation band.

    The bar is `BAR_LENGTH` cells wide, filled to the percentile rank
    rounded to the nearest cell. When history is absent, the percentile
    columns collapse to "no history" so the row still aligns with its
    siblings.
    """
    label = band.label.ljust(11)
    current = _format_multiple(band.current).rjust(7)

    if not band.has_history or band.current is None:
        return f"  {label} {current}  [dim]no historical band[/dim]"

    pct = band.percentile_rank() or 0.0
    color = _band_color(pct)
    filled = round(pct / 100 * BAR_LENGTH)
    bar = FILLED_GLYPH * filled + EMPTY_GLYPH * (BAR_LENGTH - filled)

    low = _format_multiple(band.low)
    high = _format_multiple(band.high)
    median = _format_multiple(band.median)

    return (
        f"  {label} {current}  "
        f"[{color}]{bar}[/{color}]  "
        f"{round(pct):>3}  "
        f"[dim]({low} - {high}, med {median})[/dim]"
    )


def render_panel_text(snapshot: ValuationSnapshot | None) -> Text:
    """Render the entire panel as a Rich :class:`Text`.

    Pure function so tests can assert exact output without instantiating
    a Textual widget. ``None`` (no data yet) renders a placeholder line;
    empty bands tuple renders the title + a friendly fallback.
    """
    if snapshot is None:
        return Text.from_markup("[b]Valuation[/b]\n  [dim]loading…[/dim]")
    if not snapshot.bands:
        return Text.from_markup("[b]Valuation[/b]\n  [dim]no data available[/dim]")

    lines = ["[b]Valuation[/b]"]
    for band in snapshot.bands:
        lines.append(_format_band_row(band))
    return Text.from_markup("\n".join(lines))


class ValuationPanel(Static):
    """Brief-screen widget rendering a :class:`ValuationSnapshot`.

    Constructed empty; call :meth:`set_snapshot` once the brief-loader
    worker has fetched the data. Rendering is a single :class:`Text`
    update, so swapping snapshots is cheap and flicker-free.
    """

    DEFAULT_CSS = """
    ValuationPanel {
        height: auto;
        padding: 1 1 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="valuation-panel")
        self._snapshot: ValuationSnapshot | None = None

    def on_mount(self) -> None:
        """Render the loading placeholder until the worker provides data."""
        self.update(render_panel_text(None))

    def set_snapshot(self, snapshot: ValuationSnapshot | None) -> None:
        """Replace the displayed snapshot and repaint."""
        self._snapshot = snapshot
        self.update(render_panel_text(snapshot))
