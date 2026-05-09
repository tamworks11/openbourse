"""Main screening screen — Bloomberg-style full-bleed layout.

Layout:

    ┌─ status bar ──────────────────────────────────────────┐
    │ BOURSE v…  screen://…           ●●● live  HH:MM UTC   │
    ├─ screen meta ──────────┬─ detail pane ────────────────┤
    │ description / stats    │ focused candidate's metrics  │
    ├────────────────────────┴──────────────────────────────┤
    │ TOP CANDIDATES BY COMPOSITE SCORE                     │
    │ [DataTable — fills remaining space]                   │
    ├─ command bar ─────────────────────────────────────────┤
    │ bourse> _                                             │
    ├─ footer keybinds ─────────────────────────────────────┤
    └───────────────────────────────────────────────────────┘

The command bar accepts simple line-driven commands (``lookup INTC``,
``brief CDNS``, ``screen high_growth``, ``q``). Bare tickers are treated as
``lookup TICKER`` so muscle memory matches the Bloomberg ``TKR <GO>`` flow.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static

from openbourse.domain import (
    Candidate,
    FundamentalsSnapshot,
    Instrument,
    ScreenDefinition,
    ScreenResult,
    Verdict,
)
from openbourse.providers import Providers
from openbourse.screening import BUILTIN_SCREENS, ScreeningService, format_active_filters
from openbourse.tui.widgets import StatusBar

VERDICT_STYLES: dict[Verdict, str] = {
    Verdict.STRONG_INTEREST: "bold green",
    Verdict.INTERESTING: "yellow",
    Verdict.PASS: "white",
    Verdict.REJECT: "dim red",
}

COLUMNS = (
    "#",
    "TICKER",
    "NAME",
    "PRICE",
    "MKT CAP",
    "REV GR",
    "GM",
    "FCF YLD",
    "SCORE",
    "VERDICT",
)


def _format_market_cap(cap_usd: float) -> str:
    """Compact USD market-cap formatter: 78.2B / 1.42T / 540M."""
    if cap_usd >= 1e12:
        return f"${cap_usd / 1e12:.2f}T"
    if cap_usd >= 1e9:
        return f"${cap_usd / 1e9:.1f}B"
    if cap_usd >= 1e6:
        return f"${cap_usd / 1e6:.0f}M"
    return f"${cap_usd:,.0f}"


def _format_signed_pct(value: float) -> str:
    """Signed percentage with one decimal — ``+18.4%`` or ``-3.2%``."""
    return f"{value:+.1f}%"


def _format_pct(value: float) -> str:
    """Unsigned percentage with one decimal."""
    return f"{value:.1f}%"


def _format_price(price: float | None) -> str:
    """Stock price with two decimals; em-dash when missing."""
    if price is None:
        return "—"
    return f"${price:,.2f}"


def _truncate_summary(text: str, *, max_chars: int = 280) -> str:
    """Trim a long business summary to ~``max_chars``, breaking on a sentence end.

    Yahoo/FMP descriptions are typically 600 to 1500 characters — a full
    paragraph. We want at most a couple of sentences in the detail pane so
    it doesn't crowd out the metrics. Falls back to a hard truncate with
    an ellipsis when no sentence boundary is available in the window.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    # Prefer the last complete sentence inside the window so the user sees
    # a clean ending rather than a mid-word ellipsis. Only fall back to a
    # hard truncate when the window contains no sentence boundary at all.
    boundary = window.rfind(". ")
    if boundary > 0:
        return window[: boundary + 1]
    return window.rstrip() + "…"


class ScreenerScreen(Screen[None]):
    """Renders the screen definition, summary stats, candidate table, and detail pane."""

    # Bindings shown in the footer are the discoverable subset; the others
    # ([, ], {, }) are documented in `?` help and standard enough that
    # vim users will reach for them automatically.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "view_brief", "View brief"),
        Binding("colon", "focus_command", "Command"),
        Binding("slash", "focus_command", "Command", show=False),
        Binding("d", "download_history", "Download"),
        Binding("g", "jump_top", "Top"),
        Binding("G", "jump_bottom", "Bottom"),
        Binding("[", "jump_back_25", "-25 rows", show=False),
        Binding("]", "jump_forward_25", "+25 rows", show=False),
        Binding("{", "jump_back_100", "-100 rows", show=False),
        Binding("}", "jump_forward_100", "+100 rows", show=False),
        Binding("f", "filter", "Filter"),
        Binding("s", "sort", "Sort"),
        Binding("e", "export", "Export"),
        Binding("w", "watchlist", "Watchlist"),
    ]

    def __init__(
        self,
        *,
        providers: Providers,
        screen_name: str = "quality_compounders",
        universe: Iterable[tuple[Instrument, FundamentalsSnapshot]] | None = None,
        history: dict[str, list[FundamentalsSnapshot]] | None = None,
    ) -> None:
        super().__init__()
        self._providers = providers
        self._screen: ScreenDefinition = BUILTIN_SCREENS[screen_name]
        self._universe = list(universe) if universe is not None else []
        self._history = history or {}
        self._service = ScreeningService()
        self._result: ScreenResult | None = None

    def compose(self) -> ComposeResult:
        """Build the full-bleed layout: status / split top / table / command / footer."""
        yield StatusBar(self._providers, screen_path=self._screen.name)
        yield Horizontal(
            Vertical(
                Static(self._screen_description(), id="screen-meta-text"),
                Static("", id="stats"),
                id="screen-meta",
            ),
            Vertical(
                Static("[dim](no row focused)[/dim]", id="detail-content"),
                Static("", id="detail-summary"),
                id="detail-pane",
            ),
            id="top-row",
        )
        yield Static("TOP CANDIDATES BY COMPOSITE SCORE", id="section-heading")
        yield DataTable(zebra_stripes=False, cursor_type="row", id="candidates")
        yield Horizontal(
            Input(placeholder="bourse>  type a ticker (e.g. INTC) or 'help'", id="command-input"),
            id="command-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Wire columns onto the table and run the screen for the first time."""
        table = self.query_one("#candidates", DataTable)
        table.add_columns(*COLUMNS)
        self.refresh_results()
        table.focus()

    def refresh_results(self) -> None:
        """Re-run the active screen and repaint stats, table, and detail pane."""
        self._result = self._service.run(self._screen, self._universe)
        self._render_stats(self._result)
        self._render_table(self._result)
        self._render_detail(0)

    # -- Rendering ---------------------------------------------------------

    def _screen_description(self) -> str:
        # The static ``description`` is the screen's intent; the filter line
        # below is regenerated from the current thresholds, so edits made via
        # the f-key modal are reflected on screen immediately.
        filters = format_active_filters(self._screen)
        return f"[b yellow][SCREEN][/b yellow] {self._screen.description}\n[dim]{filters}[/dim]"

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
            _format_price(snap.price_usd),
            _format_market_cap(snap.market_cap_usd),
            _format_signed_pct(snap.revenue_growth_pct),
            _format_pct(snap.gross_margin_pct),
            _format_pct(snap.fcf_yield_pct),
            str(candidate.score),
            verdict_text,
        )

    def _render_detail(self, row_index: int) -> None:
        """Repopulate the right-hand pane from the candidate at ``row_index``."""
        body = self.query_one("#detail-content", Static)
        summary_widget = self.query_one("#detail-summary", Static)
        if self._result is None or not self._result.candidates:
            body.update("[dim](no candidates)[/dim]")
            summary_widget.update("")
            return
        if row_index < 0 or row_index >= len(self._result.candidates):
            row_index = 0
        c = self._result.candidates[row_index]
        snap = c.snapshot
        verdict_style = VERDICT_STYLES[c.verdict]
        # Position indicator — useful when the candidate list is thousands long.
        position = f"[dim]{row_index + 1:,}/{len(self._result.candidates):,}[/dim]  "
        body.update(
            f"{position}[b cyan]{c.instrument.ticker}[/b cyan]  {c.instrument.name}\n"
            f"[dim]{c.instrument.sector or '—'}  ·  {c.instrument.exchange or '—'}[/dim]\n"
            f"\n"
            f"Price           {_format_price(snap.price_usd):>12}\n"
            f"Mkt cap         {_format_market_cap(snap.market_cap_usd):>12}\n"
            f"Rev growth      {_format_signed_pct(snap.revenue_growth_pct):>12}\n"
            f"Gross margin    {_format_pct(snap.gross_margin_pct):>12}\n"
            f"Net debt/EBITDA {snap.net_debt_to_ebitda:>11.2f}x\n"
            f"FCF yield       {_format_pct(snap.fcf_yield_pct):>12}\n"
            f"\n"
            f"Score [b]{c.score:>3}[/b]   "
            f"Verdict [{verdict_style}]{c.verdict.value}[/{verdict_style}]"
        )
        if c.instrument.business_summary:
            summary_widget.update(_truncate_summary(c.instrument.business_summary))
        else:
            summary_widget.update(
                "[dim]Press [b]d[/b] to download fundamentals + business description.[/dim]"
            )

    # -- Events ------------------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Update the detail pane whenever the cursor moves to a new row."""
        if event.cursor_row is not None:
            self._render_detail(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Push the brief screen when the user hits Enter on a table row.

        Textual's DataTable consumes Enter and emits ``RowSelected``; the
        screen's own ``enter`` binding never fires while the table has focus,
        so we handle this event explicitly.
        """
        if event.cursor_row is not None:
            self._open_brief_for_row(event.cursor_row)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Parse and dispatch the command typed into the bottom input."""
        if event.input.id != "command-input":
            return
        raw = event.value.strip()
        event.input.value = ""
        if not raw:
            self.query_one("#candidates", DataTable).focus()
            return
        await self._dispatch_command(raw)
        self.query_one("#candidates", DataTable).focus()

    # -- Actions -----------------------------------------------------------

    def action_focus_command(self) -> None:
        """Move focus to the bottom command input."""
        self.query_one("#command-input", Input).focus()

    # -- Fast-scroll actions ------------------------------------------------

    def _move_cursor_to(self, row: int) -> None:
        """Move the table cursor to ``row``, clamped to the candidates list."""
        if self._result is None or not self._result.candidates:
            return
        clamped = max(0, min(row, len(self._result.candidates) - 1))
        table = self.query_one("#candidates", DataTable)
        table.move_cursor(row=clamped)

    def _cursor_relative(self, delta: int) -> None:
        """Move the cursor by ``delta`` rows (positive = down)."""
        table = self.query_one("#candidates", DataTable)
        current = table.cursor_row or 0
        self._move_cursor_to(current + delta)

    def action_jump_top(self) -> None:
        """Jump to the first row."""
        self._move_cursor_to(0)

    def action_jump_bottom(self) -> None:
        """Jump to the last row."""
        if self._result is not None and self._result.candidates:
            self._move_cursor_to(len(self._result.candidates) - 1)

    def action_jump_back_25(self) -> None:
        """Move the cursor up 25 rows."""
        self._cursor_relative(-25)

    def action_jump_forward_25(self) -> None:
        """Move the cursor down 25 rows."""
        self._cursor_relative(25)

    def action_jump_back_100(self) -> None:
        """Move the cursor up 100 rows — useful for thousand-row universes."""
        self._cursor_relative(-100)

    def action_jump_forward_100(self) -> None:
        """Move the cursor down 100 rows — useful for thousand-row universes."""
        self._cursor_relative(100)

    def action_view_brief(self) -> None:
        """Open the brief screen for the row currently under the cursor."""
        table = self.query_one("#candidates", DataTable)
        if table.cursor_row is not None:
            self._open_brief_for_row(table.cursor_row)

    def _open_brief_for_row(self, row: int) -> None:
        """Push the brief screen for ``row`` in the current result set."""
        if self._result is None or not self._result.candidates:
            return
        if row < 0 or row >= len(self._result.candidates):
            return
        from openbourse.tui.screens.brief import BriefScreen

        candidate = self._result.candidates[row]
        self.app.push_screen(
            BriefScreen(
                candidate=candidate,
                providers=self._providers,
                history=self._history.get(candidate.instrument.ticker, []),
            )
        )

    def action_download_history(self) -> None:
        """Fetch + persist annual history for the row currently under the cursor.

        Runs in a background worker so the UI stays responsive while yfinance
        does its blocking work. The downloaded snapshots are persisted via
        the standard ``lookup_with_history`` path so the next TUI launch
        sees them in its startup query, and the in-memory ``_history``
        cache is updated so re-opening the brief immediately shows charts.
        """
        if self._result is None or not self._result.candidates:
            return
        table = self.query_one("#candidates", DataTable)
        if table.cursor_row is None:
            return
        candidate = self._result.candidates[table.cursor_row]
        self.run_worker(
            self._download_history_worker(candidate.instrument.ticker),
            exclusive=False,
            name=f"download-{candidate.instrument.ticker}",
        )

    async def _download_history_worker(self, ticker: str) -> None:
        """Worker body for :meth:`action_download_history`."""
        from openbourse.config import get_settings
        from openbourse.db.engine import create_engine_from_url, get_session_factory
        from openbourse.screening import TickerLookupError, lookup_with_history

        self.app.notify(
            f"Fetching history for {ticker}…",
            title="History download",
            timeout=2,
        )
        engine = create_engine_from_url(get_settings().database_url)
        factory = get_session_factory(engine)
        try:
            async with factory() as session:
                _candidate, history = await lookup_with_history(
                    ticker, self._providers, session=session
                )
        except TickerLookupError as exc:
            self.app.notify(
                str(exc),
                title="Download failed",
                severity="error",
                timeout=6,
            )
            return
        except Exception as exc:  # surface any provider/db error to the user
            self.app.notify(
                f"{type(exc).__name__}: {exc}",
                title="Download failed",
                severity="error",
                timeout=6,
            )
            return
        finally:
            await engine.dispose()

        if not history:
            self.app.notify(
                f"{ticker} has no history available from the configured provider.",
                title="No history",
                severity="warning",
                timeout=4,
            )
            return

        self._history[ticker] = history
        self.app.notify(
            f"Saved {len(history)} history points for {ticker}. Open the brief to see charts.",
            title="Download complete",
            timeout=4,
        )

    def action_filter(self) -> None:
        """Open the filter editor for the active screen.

        On Apply the screener replaces ``self._screen`` with the returned
        :class:`ScreenDefinition` and re-runs the filter — so flipping a
        Switch immediately reshapes the candidate list. Cancel returns
        ``None`` and the in-memory screen is left untouched.

        We pass the universe's distinct sectors into the editor so its
        sector toggles only show categories that are actually present in
        the loaded data — no clutter for sectors the user has no rows for.
        """
        from openbourse.tui.screens.filters import FilterEditorScreen

        self.app.push_screen(
            FilterEditorScreen(self._screen, known_sectors=self._known_sectors()),
            self._on_filter_editor_dismissed,
        )

    def _known_sectors(self) -> tuple[str, ...]:
        """Return the alphabetically-sorted distinct sectors in the universe."""
        sectors = {inst.sector for inst, _ in self._universe if inst.sector}
        return tuple(sorted(sectors))

    def _on_filter_editor_dismissed(self, new_screen: ScreenDefinition | None) -> None:
        """Apply the returned screen if any; redraw the screener."""
        if new_screen is None:
            return
        self._screen = new_screen
        self.query_one("#screen-meta-text", Static).update(self._screen_description())
        self.refresh_results()

    def action_sort(self) -> None:
        """Open the custom sort UI (not yet implemented — placeholder notice)."""
        self.app.notify("Custom sort coming soon — currently sorted by score desc.", timeout=2)

    def action_export(self) -> None:
        """Export the current candidates to CSV (not yet implemented — placeholder notice)."""
        self.app.notify("CSV export coming soon.", timeout=2)

    def action_watchlist(self) -> None:
        """Toggle the focused candidate on the watchlist (not yet implemented)."""
        self.app.notify("Watchlist actions coming soon.", timeout=2)

    # -- Command dispatch --------------------------------------------------

    async def _dispatch_command(self, raw: str) -> None:
        """Parse and execute the line typed into the command bar.

        Recognised forms:
            <TICKER>            — open brief for that ticker (alias for ``lookup``).
            lookup TICKER       — same.
            brief TICKER        — same.
            screen NAME         — switch the active screen.
            help                — show one-line help notification.
            q | quit | exit     — quit the application.
        """
        parts = raw.split()
        head = parts[0].lower()
        rest = parts[1:]

        if head in {"q", "quit", "exit"}:
            self.app.exit()
            return

        if head == "help":
            self.app.notify(
                "Commands: <TICKER> · lookup TKR · brief TKR · screen NAME · q",
                title="openbourse help",
                timeout=5,
            )
            return

        if head == "screen" and rest:
            name = rest[0]
            if name not in BUILTIN_SCREENS:
                self.app.notify(f"unknown screen: {name}", severity="error", timeout=3)
                return
            self._screen = BUILTIN_SCREENS[name]
            status = self.query_one(StatusBar)
            status.set_screen_path(self._screen.name)
            self.query_one("#screen-meta-text", Static).update(self._screen_description())
            self.refresh_results()
            return

        if head in {"lookup", "brief"} and rest:
            await self._open_brief_for_ticker(rest[0])
            return

        # Treat any single token as a ticker.
        if len(parts) == 1:
            await self._open_brief_for_ticker(parts[0])
            return

        self.app.notify(f"unknown command: {raw}", severity="warning", timeout=3)

    async def _open_brief_for_ticker(self, ticker: str) -> None:
        """Resolve ``ticker`` and fetch its history, then push the brief screen.

        Tries the in-memory history dict first (populated at app startup from
        the DB or seed). If that's empty for this ticker — typical for an
        ad-hoc lookup of an off-fixture ticker — falls through to the live
        provider history call so charts still render.
        """
        from openbourse.screening import (
            TickerLookupError,
            lookup_candidate,
            lookup_with_history,
        )
        from openbourse.tui.screens.brief import BriefScreen

        cached_history = self._history.get(ticker.upper(), [])
        try:
            if cached_history:
                candidate = await lookup_candidate(ticker, self._providers)
                history = cached_history
            else:
                candidate, history = await lookup_with_history(ticker, self._providers)
        except TickerLookupError as exc:
            self.app.notify(str(exc), title="Lookup failed", severity="error", timeout=4)
            return
        self.app.push_screen(
            BriefScreen(
                candidate=candidate,
                providers=self._providers,
                history=history,
            )
        )
