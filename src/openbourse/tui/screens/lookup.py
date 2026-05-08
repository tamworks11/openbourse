"""Modal screen for looking up an arbitrary ticker.

Returns the entered ticker (or ``None`` on cancel) via the standard Textual
``Screen.dismiss`` mechanism. Pushed by :class:`ScreenerScreen.action_lookup`.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class LookupScreen(ModalScreen[str | None]):
    """A small centred prompt that returns the typed ticker on submit."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    LookupScreen {
        align: center middle;
    }

    LookupScreen > Vertical {
        background: $boost;
        border: tall $accent;
        padding: 1 2;
        width: 50;
        height: auto;
    }

    LookupScreen Label {
        padding: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        """Render a labelled input centered on the screen."""
        yield Vertical(
            Label("Enter ticker (e.g. CDNS) and press Enter:"),
            Input(placeholder="TICKER", id="lookup-input"),
        )

    def on_mount(self) -> None:
        """Move focus to the input as soon as the modal is mounted."""
        self.query_one("#lookup-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Normalise the entered ticker and dismiss with it (or None if blank)."""
        ticker = event.value.strip().upper()
        self.dismiss(ticker or None)

    def action_cancel(self) -> None:
        """Dismiss the modal without returning a ticker."""
        self.dismiss(None)
