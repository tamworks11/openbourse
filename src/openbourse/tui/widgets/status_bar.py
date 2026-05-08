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

    def _provider_marker(self) -> str:
        kind = "stub" if self._providers.using_stubs else "live"
        return f"● FMP {kind}  ● EDGAR {kind}  ● Claude {kind}"

    def _refresh_text(self) -> None:
        timestamp = self.now.strftime("%Y-%m-%d %H:%M:%S")
        self._left.update(
            f"[b]BOURSE[/b] v{__version__}    [dim]screen://[/dim][b]{self._screen_path or '-'}[/b]"
        )
        self._right.update(f"{self._provider_marker()}    {timestamp} UTC")
