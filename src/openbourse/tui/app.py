"""Top-level Textual application."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from textual.app import App
from textual.binding import BindingType

from openbourse.providers import Providers, build_providers
from openbourse.tui.screens.screener import ScreenerScreen


class BourseApp(App[None]):
    """The ``bourse`` Textual application."""

    CSS_PATH = Path(__file__).parent / "styles.tcss"
    TITLE = "openbourse"
    SUB_TITLE = "equity research workstation"
    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("?", "help", "Help"),
    ]

    def __init__(
        self,
        *,
        providers: Providers | None = None,
        universe: list[tuple[Any, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.providers = providers or build_providers()
        self._universe = universe

    def on_mount(self) -> None:
        """Push the screener as the initial screen."""
        self.push_screen(ScreenerScreen(providers=self.providers, universe=self._universe))

    def action_help(self) -> None:
        """Surface a one-line keybinding cheat sheet via Textual's notify popup."""
        self.notify(
            "Keys: ↑↓ navigate · enter view brief · f filter · s sort · "
            "e export · w watchlist · q quit",
            title="openbourse help",
            timeout=8,
        )
