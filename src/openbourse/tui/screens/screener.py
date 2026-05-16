"""Main screening screen — Bloomberg-style full-bleed layout.

Layout:

    ┌─ status bar ──────────────────────────────────────────┐
    │ OPENBOURSE v…  screen://…       ●●● live  HH:MM UTC   │
    ├─ screen meta ──────────┬─ detail pane ────────────────┤
    │ description / stats    │ focused candidate's metrics  │
    ├────────────────────────┴──────────────────────────────┤
    │ TOP CANDIDATES BY COMPOSITE SCORE                     │
    │ [DataTable — fills remaining space]                   │
    ├─ command bar ─────────────────────────────────────────┤
    │ openbourse> _                                         │
    ├─ footer keybinds ─────────────────────────────────────┤
    └───────────────────────────────────────────────────────┘

The command bar accepts simple line-driven commands (``lookup INTC``,
``brief CDNS``, ``screen high_growth``, ``q``). Bare tickers are treated as
``lookup TICKER`` so muscle memory matches the Bloomberg ``TKR <GO>`` flow.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static

from openbourse.domain import (
    Candidate,
    FundamentalsSnapshot,
    Instrument,
    Quote,
    ScreenDefinition,
    ScreenResult,
    Verdict,
)
from openbourse.providers import Providers
from openbourse.screening import (
    BUILTIN_SCREENS,
    ScreeningService,
    compute_style_fit,
    format_active_filters,
)
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
    "VOLUME",
    "MKT CAP",
    "REV GR",
    "GM",
    "FCF YLD",
    "SCORE",
    "RISK",
    "VERDICT",
)


# Band thresholds match the bands documented in README.md and brief.svg:
# 0-30 low (green), 30-60 moderate (yellow), 60-100 high (red).
def _risk_glyph_color(risk_score: int) -> str:
    """Return the Rich colour name for the band ``risk_score`` falls into."""
    if risk_score <= 30:
        return "green"
    if risk_score < 60:
        return "yellow"
    return "red"


def _risk_cell(risk_score: int) -> Text:
    """Build a coloured-glyph + number cell for the candidates table.

    ● glyph picks a green / yellow / red tint based on the risk band so
    the user can scan the column at a glance without reading the digits.
    """
    color = _risk_glyph_color(risk_score)
    cell = Text()
    cell.append("● ", style=color)
    cell.append(f"{risk_score:>3}")
    return cell


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


def _format_volume(volume: int | None) -> str:
    """Compact share-volume formatter: 1.40B / 12.3M / 850K / 1,234.

    ``None`` renders as an em-dash — Yahoo doesn't return a volume for
    every ticker (thinly traded names, some ADRs), and the poll worker
    only records it when present.
    """
    if volume is None:
        return "—"
    if volume >= 1_000_000_000:
        return f"{volume / 1_000_000_000:.2f}B"
    if volume >= 1_000_000:
        return f"{volume / 1_000_000:.1f}M"
    if volume >= 1_000:
        return f"{volume / 1_000:.0f}K"
    return f"{volume:,}"


def _format_change(value: float | None) -> str:
    """Signed absolute price change: +$2.34 / -$1.05 / em-dash when missing."""
    if value is None:
        return "—"
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"


def _format_signed_pct_opt(value: float | None) -> str:
    """Signed percentage, em-dash when missing — None-aware ``_format_signed_pct``."""
    return "—" if value is None else _format_signed_pct(value)


def _format_pe(pe: float | None) -> str:
    """Trailing P/E ratio to one decimal; em-dash when missing or non-positive."""
    if pe is None or pe <= 0:
        return "—"
    return f"{pe:.1f}"


def _detail_row(left: tuple[str, str], right: tuple[str, str] | None) -> str:
    """Format one or two ``(label, value)`` pairs as a detail-pane line.

    Two metrics per line keeps the detail pane compact enough to show the
    full market + fundamentals set without overflowing its fixed height.
    """
    label_l, value_l = left
    cell = f"{label_l:<15}{value_l:>11}"
    if right is None:
        return cell
    label_r, value_r = right
    return f"{cell}   {label_r:<15}{value_r:>11}"


def _select_tickers_to_poll(
    candidates: Sequence[Candidate],
    *,
    visible_first: int,
    visible_last: int,
    cursor: int | None,
    padding: int,
    cap: int,
) -> list[str]:
    """Pick the candidate tickers to fetch on the next quote poll.

    Pure function so the row-window math stays unit-testable without a
    live DataTable. Combines:

    * The visible row range ``[visible_first, visible_last)``.
    * ``padding`` rows on each side, clamped to the candidates list.
    * The cursor's row (always included so a programmatic jump or focus
      change can't leave the detail pane stuck on a stale price).

    Capped at ``cap`` total tickers to prevent runaway upstream requests
    on extra-tall terminals.
    """
    total = len(candidates)
    if total == 0:
        return []
    start = max(0, visible_first - padding)
    end = min(total, visible_last + padding)
    indices: set[int] = set(range(start, end)) if end > start else set()
    if cursor is not None and 0 <= cursor < total:
        indices.add(cursor)
    sorted_indices = sorted(indices)[:cap]
    return [candidates[i].instrument.ticker for i in sorted_indices]


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

    # Hard cap on tickers polled per refresh cycle, regardless of how
    # many are visible. yfinance has no batch endpoint and Yahoo throttles
    # past ~30 req/min from a single client, so even a tall terminal
    # showing 200+ rows shouldn't trigger a 200-request burst.
    QUOTE_POLL_TICKER_CAP: ClassVar[int] = 100
    # Rows polled above/below the visible window. With 20 rows of padding,
    # a single PgDn lands on already-fresh prices instead of waiting a
    # full poll cycle.
    QUOTE_POLL_VIEWPORT_PADDING: ClassVar[int] = 20
    # Column indices into COLUMNS: # | TICKER | NAME | PRICE | VOLUME | …
    PRICE_COLUMN_INDEX: ClassVar[int] = 3
    VOLUME_COLUMN_INDEX: ClassVar[int] = 4
    # How often the TUI re-reads the DB's last-sync timestamp, so a sync
    # that completes while the app is open (e.g. the scheduled pre-market
    # run) updates the status bar without a restart.
    DB_SYNC_POLL_SECONDS: ClassVar[int] = 60

    def __init__(
        self,
        *,
        providers: Providers,
        screen_name: str = "quality_compounders",
        universe: Iterable[tuple[Instrument, FundamentalsSnapshot]] | None = None,
        history: dict[str, list[FundamentalsSnapshot]] | None = None,
        last_synced_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._providers = providers
        self._screen: ScreenDefinition = BUILTIN_SCREENS[screen_name]
        self._universe = list(universe) if universe is not None else []
        self._history = history or {}
        self._last_synced_at = last_synced_at
        self._service = ScreeningService()
        self._result: ScreenResult | None = None
        # Latest live quote per ticker from the poll worker. Sparse — only
        # polled tickers appear. The table cells and detail pane prefer
        # this over the snapshot's stale price when a quote is present.
        self._latest_quotes: dict[str, Quote] = {}

    def compose(self) -> ComposeResult:
        """Build the full-bleed layout: status / split top / table / command / footer."""
        yield StatusBar(
            self._providers,
            screen_path=self._screen.name,
            last_synced_at=self._last_synced_at,
        )
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
            Input(
                placeholder="openbourse>  type a ticker (e.g. INTC) or 'help'", id="command-input"
            ),
            id="command-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Wire columns onto the table, run the first screen, start the poll loops."""
        table = self.query_one("#candidates", DataTable)
        table.add_columns(*COLUMNS)
        self.refresh_results()
        table.focus()
        self._start_quote_polling()
        self._start_db_sync_polling()

    def _start_quote_polling(self) -> None:
        """Schedule a periodic worker to refresh prices in place.

        Reads ``OPENBOURSE_QUOTE_REFRESH_SECONDS`` from settings. ``0``
        disables polling entirely; positive values create a ``set_interval``
        loop that fires the worker. The first poll runs immediately so
        the user doesn't have to wait the full interval to see live data.
        """
        from openbourse.config import get_settings

        interval = get_settings().quote_refresh_seconds
        status = self.query_one(StatusBar)
        if interval <= 0:
            status.mark_quotes_disabled()
            return
        # Fire one poll immediately, then schedule the recurring tick.
        self.run_worker(self._poll_quotes(), name="quote_poll", exclusive=False)
        self.set_interval(interval, self._schedule_quote_poll)

    def _schedule_quote_poll(self) -> None:
        """Fire-and-forget the polling worker on each tick of the timer."""
        self.run_worker(self._poll_quotes(), name="quote_poll", exclusive=False)

    def _start_db_sync_polling(self) -> None:
        """Schedule a periodic re-read of the DB's last-sync timestamp.

        Keeps the status bar's "DB synced" marker current when a sync
        finishes — e.g. the scheduled pre-market run — while the TUI is
        already open. The first poll fires immediately so a sync that
        completed between app launch and now is picked up at once.
        """
        self.run_worker(self._poll_db_sync(), name="db_sync_poll", exclusive=False)
        self.set_interval(self.DB_SYNC_POLL_SECONDS, self._schedule_db_sync_poll)

    def _schedule_db_sync_poll(self) -> None:
        """Fire-and-forget the DB-sync poll worker on each tick of the timer."""
        self.run_worker(self._poll_db_sync(), name="db_sync_poll", exclusive=False)

    async def _poll_db_sync(self) -> None:
        """Read the latest sync timestamp from the DB and update the status bar.

        Failures are silent — if the database is briefly unreachable the
        marker keeps its last known value and the next tick retries.
        """
        from openbourse.config import get_settings
        from openbourse.db.engine import create_engine_from_url, get_session_factory
        from openbourse.db.repositories import SyncRunRepository

        try:
            engine = create_engine_from_url(get_settings().database_url)
            factory = get_session_factory(engine)
            try:
                async with factory() as session:
                    latest = await SyncRunRepository(session).latest()
            finally:
                await engine.dispose()
        except Exception:
            return
        self.query_one(StatusBar).update_db_synced(latest.synced_at if latest else None)

    async def _poll_quotes(self) -> None:
        """Fetch fresh prices for the visible rows and update the table.

        Polls the rows currently visible in the DataTable, padded above
        and below by :attr:`QUOTE_POLL_VIEWPORT_PADDING` so a quick
        scroll/jump lands on already-fresh prices. Hard-capped at
        :attr:`QUOTE_POLL_TICKER_CAP` to protect against extra-tall
        terminals. Each poll is independent — failures are silent and
        the next tick simply tries again. On success the status bar's
        "Quotes" marker is updated so the user sees the freshness lag.
        """
        if self._result is None or not self._result.candidates:
            return
        tickers = self._tickers_to_poll()
        if not tickers:
            return
        try:
            quotes = await self._providers.quotes.fetch_quotes(tickers)
        except Exception:
            return
        if not quotes:
            return
        for ticker, quote in quotes.items():
            self._latest_quotes[ticker] = quote
        self._apply_quote_overrides_to_table(quotes)
        # Refresh the detail pane if the focused row's price moved — the
        # detail pane reads from the candidate snapshot otherwise, missing
        # the override.
        if self._focused_ticker() in quotes:
            row_index = self._focused_row_index()
            if row_index is not None:
                self._render_detail(row_index)

        latest = max((q.fetched_at for q in quotes.values()), default=None)
        self.query_one(StatusBar).mark_quote_polled(latest)

    def _tickers_to_poll(self) -> list[str]:
        """Return the candidate tickers to refresh on the next poll cycle.

        Reads the DataTable's current scroll position, computes which
        candidate rows are inside the visible window (plus padding), and
        always includes the cursor's row so the focused detail pane
        stays fresh regardless of scroll. Capped at
        :attr:`QUOTE_POLL_TICKER_CAP` to protect against extra-tall
        terminals or huge viewports.
        """
        if self._result is None or not self._result.candidates:
            return []
        first, last = self._visible_row_range()
        return _select_tickers_to_poll(
            self._result.candidates,
            visible_first=first,
            visible_last=last,
            cursor=self._focused_row_index(),
            padding=self.QUOTE_POLL_VIEWPORT_PADDING,
            cap=self.QUOTE_POLL_TICKER_CAP,
        )

    def _visible_row_range(self) -> tuple[int, int]:
        """Return (first, last) row indices currently rendered in the viewport.

        Last is exclusive — i.e., ``range(first, last)`` enumerates the
        rows on screen. Falls back to a 0-row range when the DataTable
        isn't mounted yet (early ticks during composition).
        """
        try:
            table = self.query_one("#candidates", DataTable)
        except Exception:
            return (0, 0)
        scroll_y = int(table.scroll_y)
        # Subtract one for the column-header row that always sits on top.
        visible_height = max(0, table.size.height - 1)
        return (scroll_y, scroll_y + visible_height)

    def _apply_quote_overrides_to_table(self, quotes: Mapping[str, object]) -> None:
        """Update the price and volume cells of every freshly-quoted row.

        Indexes cells positionally against ``self._result.candidates``,
        which is the same order ``_render_table`` painted them in.
        """
        if self._result is None:
            return
        table = self.query_one("#candidates", DataTable)
        for row_index, candidate in enumerate(self._result.candidates):
            ticker = candidate.instrument.ticker
            if ticker not in quotes:
                continue
            quote = self._latest_quotes.get(ticker)
            if quote is None:
                continue
            try:
                table.update_cell_at(
                    Coordinate(row_index, self.PRICE_COLUMN_INDEX),
                    _format_price(quote.price_usd),
                )
                table.update_cell_at(
                    Coordinate(row_index, self.VOLUME_COLUMN_INDEX),
                    _format_volume(quote.volume),
                )
            except Exception:
                continue

    def _focused_ticker(self) -> str | None:
        """Return the ticker of the cursor's row, or ``None`` if no focus."""
        if self._result is None or not self._result.candidates:
            return None
        idx = self._focused_row_index()
        if idx is None:
            return None
        return self._result.candidates[idx].instrument.ticker

    def _focused_row_index(self) -> int | None:
        """Return the cursor's row index, or ``None`` if the table is empty."""
        if self._result is None or not self._result.candidates:
            return None
        try:
            table = self.query_one("#candidates", DataTable)
        except Exception:
            return None
        cursor = table.cursor_row
        if cursor < 0 or cursor >= len(self._result.candidates):
            return None
        return cursor

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
        # Prefer the latest live quote if we have one — keeps the initial
        # paint consistent with whatever the polling loop has already
        # fetched, instead of flashing the snapshot price first.
        quote = self._latest_quotes.get(candidate.instrument.ticker)
        price = quote.price_usd if quote is not None else snap.price_usd
        volume = quote.volume if quote is not None else None
        return (
            f"{index:02d}",
            candidate.instrument.ticker,
            candidate.instrument.name,
            _format_price(price),
            _format_volume(volume),
            _format_market_cap(snap.market_cap_usd),
            _format_signed_pct(snap.revenue_growth_pct),
            _format_pct(snap.gross_margin_pct),
            _format_pct(snap.fcf_yield_pct),
            str(candidate.score),
            _risk_cell(candidate.risk_score),
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
        fit_pct = compute_style_fit(snap, self._screen)
        # Prefer the latest live quote if we have one; this is what's
        # already showing in the table column, so keeping the detail pane
        # consistent prevents "$35.37 in the table, $34.91 in the pane".
        # Change / Change % / Avg Vol (3M) / 52 Wk Change are quote-only —
        # an em-dash until the row has been polled.
        quote = self._latest_quotes.get(c.instrument.ticker)
        price = quote.price_usd if quote is not None else snap.price_usd
        # Quote-only fields — None until the row has been polled.
        q_change = quote.change if quote is not None else None
        q_change_pct = quote.change_pct if quote is not None else None
        q_volume = quote.volume if quote is not None else None
        q_avg_vol = quote.avg_volume_3m if quote is not None else None
        q_52wk = quote.year_change_pct if quote is not None else None
        metrics: list[tuple[str, str]] = [
            ("Price", _format_price(price)),
            ("Change", _format_change(q_change)),
            ("Change %", _format_signed_pct_opt(q_change_pct)),
            ("Volume", _format_volume(q_volume)),
            ("Avg Volume (3M)", _format_volume(q_avg_vol)),
            ("Market Cap", _format_market_cap(snap.market_cap_usd)),
            ("PE Ratio (TTM)", _format_pe(snap.pe_ratio_ttm)),
            ("52 Wk Change %", _format_signed_pct_opt(q_52wk)),
            ("Rev growth", _format_signed_pct(snap.revenue_growth_pct)),
            ("Gross margin", _format_pct(snap.gross_margin_pct)),
            ("Net debt/EBITDA", f"{snap.net_debt_to_ebitda:.2f}x"),
            ("FCF yield", _format_pct(snap.fcf_yield_pct)),
        ]
        metric_lines = "\n".join(
            _detail_row(metrics[i], metrics[i + 1] if i + 1 < len(metrics) else None)
            for i in range(0, len(metrics), 2)
        )
        body.update(
            f"{position}[b cyan]{c.instrument.ticker}[/b cyan]  {c.instrument.name}\n"
            f"[dim]{c.instrument.sector or '—'}  ·  {c.instrument.exchange or '—'}[/dim]\n"
            f"\n"
            f"{metric_lines}\n"
            f"\n"
            f"Score [b]{c.score:>3}[/b]   "
            f"Risk [b {_risk_glyph_color(c.risk_score)}]"
            f"{c.risk_score:>3}[/b {_risk_glyph_color(c.risk_score)}]   "
            f"Fit [b]{fit_pct:>3.0f}%[/b]   "
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
                screen=self._screen,
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
                screen=self._screen,
            )
        )
