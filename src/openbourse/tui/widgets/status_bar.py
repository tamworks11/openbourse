"""Top status bar widget — version, provider health, current time."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Static

from openbourse import __version__
from openbourse.providers import Providers

# A DB sync older than this many *weekday* seconds turns the status-bar
# marker yellow. Weekend time is excluded (see ``_weekday_seconds``) so a
# Friday-evening sync isn't flagged stale on a Saturday.
DB_STALE_AFTER_SECONDS = 2 * 60 * 60  # 2 hours


def _weekday_seconds(start: datetime, end: datetime) -> float:
    """Seconds elapsed between ``start`` and ``end``, counting Mon-Fri only.

    Saturday and Sunday (UTC) are excluded, so the staleness check doesn't
    fire purely because the market — and the scheduled sync — paused over
    the weekend. Returns ``0.0`` when ``end`` is at or before ``start``.
    """
    if end <= start:
        return 0.0
    total = 0.0
    cursor = start
    while cursor < end:
        # Walk one calendar day at a time so each segment has a single,
        # well-defined weekday.
        next_midnight = (cursor + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        segment_end = min(next_midnight, end)
        if cursor.weekday() < 5:  # Mon=0 … Fri=4; Sat/Sun excluded
            total += (segment_end - cursor).total_seconds()
        cursor = segment_end
    return total


class StatusBar(Vertical):
    """Two-row header.

    Row 1 — identity: ``OPENBOURSE v… screen://…`` on the left, the live
    UTC clock on the right.

    Row 2 — data freshness: the DB-sync marker on the left, provider-mode
    markers + quote-poll freshness on the right.

    Splitting across two rows is deliberate: a single row couldn't fit
    the DB-sync marker without truncating it on normal-width terminals.
    """

    DEFAULT_CSS = ""
    now: reactive[datetime] = reactive(lambda: datetime.now(UTC))

    def __init__(
        self,
        providers: Providers,
        screen_path: str = "",
        last_synced_at: datetime | None = None,
    ) -> None:
        super().__init__(id="status-bar")
        self._providers = providers
        self._screen_path = screen_path
        # UTC time of the last `bourse universe sync`; None = never synced.
        self._last_synced_at = last_synced_at
        # Row 1 — identity + clock.
        self._row1_left = Static("", classes="left", id="status-identity")
        self._row1_right = Static("", classes="right", id="status-clock")
        # Row 2 — DB-sync marker + provider/quote markers.
        self._row2_left = Static("", classes="left", id="status-db-sync")
        self._row2_right = Static("", classes="right", id="status-providers")
        # Last successful quote-poll timestamp, surfaced as "Quotes · 12s ago".
        # ``None`` means no successful poll yet (or polling disabled); the
        # marker shows "off" in that case.
        self._last_quote_at: datetime | None = None
        self._quotes_disabled: bool = False

    def compose(self) -> Iterable[Horizontal]:
        """Yield the two header rows, each a left/right Horizontal."""
        yield Horizontal(self._row1_left, self._row1_right, classes="status-row")
        yield Horizontal(self._row2_left, self._row2_right, classes="status-row")

    def on_mount(self) -> None:
        """Schedule the once-per-second clock tick and paint the initial text."""
        self.set_interval(1.0, self._tick)
        self._refresh_text()

    def _tick(self) -> None:
        """Advance the displayed clock; the reactive watcher then repaints."""
        self.now = datetime.now(UTC)
        self._refresh_text()

    def watch_now(self, _: datetime) -> None:
        """Reactive hook — repaint whenever the ``now`` attribute changes."""
        self._refresh_text()

    def set_screen_path(self, path: str) -> None:
        """Update the ``screen://...`` indicator shown on the left half."""
        self._screen_path = path
        self._refresh_text()

    def mark_quote_polled(self, when: datetime | None) -> None:
        """Record a successful (or failed) poll timestamp.

        ``when=None`` indicates polling is disabled — the status marker
        renders "Quotes off" so users know the price column won't tick
        without manual refresh. Otherwise the marker shows the elapsed
        time since the last successful poll.
        """
        self._last_quote_at = when
        self._refresh_text()

    def mark_quotes_disabled(self) -> None:
        """Latch the "Quotes off" state so subsequent ticks don't reset it."""
        self._quotes_disabled = True
        self._last_quote_at = None
        self._refresh_text()

    def update_db_synced(self, when: datetime | None) -> None:
        """Update the recorded DB-sync time and repaint the marker.

        Called by the screener's poll worker so a sync that completes
        (e.g. the scheduled pre-market run) while the TUI is open is
        reflected without a restart. ``None`` leaves it "never synced".
        """
        self._last_synced_at = when
        self._refresh_text()

    def _db_sync_marker(self, now: datetime) -> str:
        """Render the "DB synced …" indicator shown on the left half.

        The leading ``●`` is red when the database was never synced,
        yellow once the last sync is more than :data:`DB_STALE_AFTER_SECONDS`
        of weekday time old, and green while the data is fresh.
        """
        if self._last_synced_at is None:
            return "[red]●[/red] [red]DB never synced[/red]"
        stamp = self._last_synced_at.strftime("%Y-%m-%d %H:%M")
        if _weekday_seconds(self._last_synced_at, now) > DB_STALE_AFTER_SECONDS:
            return f"[yellow]●[/yellow] [yellow]DB synced[/yellow] {stamp} UTC"
        return f"[green]●[/green] [dim]DB synced[/dim] {stamp} UTC"

    def _provider_marker(self) -> str:
        return (
            f"● FMP {self._providers.fundamentals_mode}  "
            f"● EDGAR {self._providers.filings_mode}  "
            f"● Claude {self._providers.brief_mode}  "
            f"● {self._quote_marker()}"
        )

    def _quote_marker(self) -> str:
        """Render the right-most "Quotes · …" indicator."""
        if self._quotes_disabled:
            return "Quotes off"
        if self._last_quote_at is None:
            return "Quotes …"
        elapsed = (self.now - self._last_quote_at).total_seconds()
        if elapsed < 0:
            elapsed = 0
        if elapsed < 60:
            label = f"{int(elapsed)}s ago"
        elif elapsed < 3600:
            label = f"{int(elapsed // 60)}m ago"
        else:
            label = f"{int(elapsed // 3600)}h ago"
        return f"Quotes · {label}"

    def _refresh_text(self) -> None:
        timestamp = self.now.strftime("%Y-%m-%d %H:%M:%S")
        # Row 1 — identity (left) + clock (right).
        self._row1_left.update(
            f"[b]OPENBOURSE[/b] v{__version__}    "
            f"[dim]screen://[/dim][b]{self._screen_path or '-'}[/b]"
        )
        self._row1_right.update(f"{timestamp} UTC")
        # Row 2 — DB-sync freshness (left) + provider/quote markers (right).
        self._row2_left.update(self._db_sync_marker(self.now))
        self._row2_right.update(self._provider_marker())
