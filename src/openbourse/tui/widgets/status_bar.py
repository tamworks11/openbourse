"""Top status bar widget — version, provider health, current time."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static

from openbourse import __version__
from openbourse.providers import Providers


class StatusBar(Horizontal):
    """Two-row header: title/providers/time on top, screen path on bottom."""

    DEFAULT_CSS = ""
    now: reactive[datetime] = reactive(lambda: datetime.now(UTC))

    def __init__(self, providers: Providers, screen_path: str = "") -> None:
        super().__init__(id="status-bar")
        self._providers = providers
        self._screen_path = screen_path
        self._left = Static("", classes="left", id="status-left")
        self._right = Static("", classes="right", id="status-right")
        # Last successful quote-poll timestamp, surfaced as "Quotes · 12s ago".
        # ``None`` means no successful poll yet (or polling disabled); the
        # marker shows "off" in that case.
        self._last_quote_at: datetime | None = None
        self._quotes_disabled: bool = False

    def compose(self) -> Iterable[Static]:
        """Yield the left (title/path) and right (providers/clock) halves."""
        yield self._left
        yield self._right

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
        self._left.update(
            f"[b]BOURSE[/b] v{__version__}    [dim]screen://[/dim][b]{self._screen_path or '-'}[/b]"
        )
        self._right.update(f"{self._provider_marker()}    {timestamp} UTC")
