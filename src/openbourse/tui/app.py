"""Top-level Textual application."""

from __future__ import annotations

from datetime import datetime
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
        history: dict[str, list[Any]] | None = None,
        last_synced_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self.providers = providers or build_providers()
        self._universe = universe
        self._history = history or {}
        self._last_synced_at = last_synced_at

    def on_mount(self) -> None:
        """Push the screener as the initial screen."""
        self.push_screen(
            ScreenerScreen(
                providers=self.providers,
                universe=self._universe,
                history=self._history,
                last_synced_at=self._last_synced_at,
            )
        )

    def action_help(self) -> None:
        """Surface a one-line keybinding cheat sheet via Textual's notify popup.

        ``notify`` runs the message through Rich markup, so any literal ``[``
        or ``]`` inside the text needs escaping with a leading backslash —
        otherwise ``[/]`` is read as a closing-tag and the renderer crashes.
        """
        self.notify(
            r"Keys: ↑↓ row · pgUp/pgDn page · g/G top/bottom · "
            r"\[ / \] ±25 · { / } ±100 · "
            r"↵ brief · / command · d download · q quit",
            title="openbourse keys",
            timeout=10,
        )
