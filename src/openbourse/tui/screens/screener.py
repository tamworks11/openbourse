"""Main screening screen — replicates the layout from the project README."""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Static

from openbourse.domain import (
    Candidate,
    FundamentalsSnapshot,
    Instrument,
    ScreenDefinition,
    ScreenResult,
    Verdict,
)
from openbourse.providers import Providers
from openbourse.screening import BUILTIN_SCREENS, ScreeningService
from openbourse.tui.widgets import StatusBar

VERDICT_STYLES: dict[Verdict, str] = {
    Verdict.STRONG_INTEREST: "bold green",
    Verdict.INTERESTING: "yellow",
    Verdict.PASS: "white",
    Verdict.REJECT: "dim",
}

COLUMNS = ("#", "TICKER", "NAME", "MKT CAP", "REV GR", "GM", "FCF YLD", "SCORE", "VERDICT")


def _format_market_cap(cap_usd: float) -> str:
    if cap_usd >= 1e12:
        return f"${cap_usd / 1e12:.2f}T"
    if cap_usd >= 1e9:
        return f"${cap_usd / 1e9:.1f}B"
    if cap_usd >= 1e6:
        return f"${cap_usd / 1e6:.0f}M"
    return f"${cap_usd:,.0f}"


def _format_signed_pct(value: float) -> str:
    return f"{value:+.1f}%"


def _format_pct(value: float) -> str:
    return f"{value:.1f}%"


class ScreenerScreen(Screen[None]):
    """Renders the screen definition, summary stats, and candidate table."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "view_brief", "View brief"),
        ("f", "filter", "Filter"),
        ("s", "sort", "Sort"),
        ("e", "export", "Export"),
        ("w", "watchlist", "Watchlist"),
    ]

    def __init__(
        self,
        *,
        providers: Providers,
        screen_name: str = "quality_compounders",
        universe: Iterable[tuple[Instrument, FundamentalsSnapshot]] | None = None,
    ) -> None:
        super().__init__()
        self._providers = providers
        self._screen: ScreenDefinition = BUILTIN_SCREENS[screen_name]
        self._universe = list(universe) if universe is not None else []
        self._service = ScreeningService()
        self._result: ScreenResult | None = None

    def compose(self) -> ComposeResult:
        """Build the layout: status bar, screen metadata, results table, footer."""
        yield StatusBar(self._providers, screen_path=self._screen.name)
        yield Vertical(
            Static(self._screen_description(), id="screen-meta"),
            Static("", id="stats"),
            Static("TOP CANDIDATES BY COMPOSITE SCORE", id="section-heading"),
            DataTable(zebra_stripes=False, cursor_type="row", id="candidates"),
        )
        yield Footer()

    def on_mount(self) -> None:
        """Wire columns onto the table and run the screen for the first time."""
        table = self.query_one("#candidates", DataTable)
        table.add_columns(*COLUMNS)
        self.refresh_results()

    def refresh_results(self) -> None:
        """Re-run the active screen and repaint stats + table."""
        self._result = self._service.run(self._screen, self._universe)
        self._render_stats(self._result)
        self._render_table(self._result)

    def _screen_description(self) -> str:
        return f"[b yellow][SCREEN][/b yellow] {self._screen.description}"

    def _render_stats(self, result: ScreenResult) -> None:
        analyzed = min(result.filtered_count, 12)
        stats = self.query_one("#stats", Static)
        stats.update(
            f"Universe: [b]{result.universe_size:,}[/b] instruments  ·  "
            f"Filtered: [b]{result.filtered_count}[/b] candidates  ·  "
            f"Analyzed: [b]{analyzed}[/b] with AI briefs"
        )

    def _render_table(self, result: ScreenResult) -> None:
        table = self.query_one("#candidates", DataTable)
        table.clear()
        for idx, candidate in enumerate(result.candidates, start=1):
            table.add_row(*self._row_for(idx, candidate))

    def _row_for(self, index: int, candidate: Candidate) -> tuple[str | Text, ...]:
        snap = candidate.snapshot
        verdict_text = Text(candidate.verdict.value, style=VERDICT_STYLES[candidate.verdict])
        return (
            f"{index:02d}",
            candidate.instrument.ticker,
            candidate.instrument.name,
            _format_market_cap(snap.market_cap_usd),
            _format_signed_pct(snap.revenue_growth_pct),
            _format_pct(snap.gross_margin_pct),
            _format_pct(snap.fcf_yield_pct),
            str(candidate.score),
            verdict_text,
        )

    def action_view_brief(self) -> None:
        """Open the brief screen for the row currently under the cursor."""
        if self._result is None or not self._result.candidates:
            return
        table = self.query_one("#candidates", DataTable)
        row = table.cursor_row
        if row is None or row >= len(self._result.candidates):
            return
        from openbourse.tui.screens.brief import BriefScreen

        candidate = self._result.candidates[row]
        self.app.push_screen(BriefScreen(candidate=candidate, providers=self._providers))

    def action_filter(self) -> None:
        """Open the interactive filter editor (not yet implemented — placeholder notice)."""
        self.app.notify("Filter editor coming soon.", timeout=2)

    def action_sort(self) -> None:
        """Open the custom sort UI (not yet implemented — placeholder notice)."""
        self.app.notify("Custom sort coming soon — currently sorted by score desc.", timeout=2)

    def action_export(self) -> None:
        """Export the current candidates to CSV (not yet implemented — placeholder notice)."""
        self.app.notify("CSV export coming soon.", timeout=2)

    def action_watchlist(self) -> None:
        """Toggle the focused candidate on the watchlist (not yet implemented)."""
        self.app.notify("Watchlist actions coming soon.", timeout=2)
