"""Modal screen for editing the active screen's filter thresholds.

Each criterion has a Switch (enabled/disabled) and an Input (threshold).
Disabling a criterion sets its field to ``None`` on the resulting
:class:`ScreenDefinition`, which :func:`passes_screen` short-circuits
to "always pass" for that one rule. The other criteria continue filtering.

The modal returns the new ``ScreenDefinition`` on Apply (or ``None`` on
Cancel) via Textual's standard ``Screen.dismiss`` mechanism.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static, Switch

from openbourse.domain import ScreenDefinition, Verdict


def _sector_toggle_id(sector: str) -> str:
    """Sector names contain spaces and ampersands; translate to a CSS-safe id.

    Reversal isn't required — the editor only writes these IDs and looks
    them up by the same transform when reading switch state back out.
    """
    safe = "".join(c.lower() if c.isalnum() else "-" for c in sector)
    return f"toggle-sector-{safe}"


class FilterEditorScreen(ModalScreen[ScreenDefinition | None]):
    """Modal that lets the user toggle and tune the active screen's filters."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    FilterEditorScreen {
        align: center middle;
    }

    FilterEditorScreen > Vertical {
        background: $boost;
        border: tall $accent;
        padding: 1 2;
        width: 76;
        height: auto;
    }

    FilterEditorScreen #filter-title {
        color: $accent;
        text-style: bold;
        padding: 0 0 1 0;
    }

    FilterEditorScreen #filter-desc {
        color: $text-muted;
        padding: 0 0 1 0;
    }

    FilterEditorScreen .filter-row {
        height: 3;
        align: left middle;
    }

    FilterEditorScreen .filter-row Switch {
        margin-right: 1;
    }

    FilterEditorScreen .filter-row Label {
        width: auto;
        margin: 0 1;
    }

    FilterEditorScreen .filter-row .field-label {
        width: 22;
    }

    FilterEditorScreen .filter-row .op {
        width: 3;
        text-align: center;
    }

    FilterEditorScreen .filter-row Input {
        width: 12;
    }

    FilterEditorScreen .filter-row .unit {
        width: 4;
    }

    FilterEditorScreen #verdict-section-header,
    FilterEditorScreen #sector-section-header {
        margin-top: 1;
        color: $accent;
        text-style: bold;
    }

    FilterEditorScreen #filter-buttons {
        margin-top: 1;
        height: 3;
        align: center middle;
    }

    FilterEditorScreen #filter-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        screen: ScreenDefinition,
        *,
        known_sectors: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._screen = screen
        # ``known_sectors`` is the alphabetically-sorted set of sector names
        # actually present in the loaded universe — we don't show toggles
        # for sectors the user has no data for. Empty tuple → no sector
        # section at all.
        self._known_sectors = tuple(known_sectors)

    def compose(self) -> ComposeResult:
        """Render the modal: title, description, one row per criterion, buttons."""
        yield Vertical(
            Static(f"Edit filters: {self._screen.name}", id="filter-title"),
            Static(self._screen.description, id="filter-desc"),
            *self._criterion_rows(),
            Horizontal(
                Button("Apply", variant="primary", id="apply"),
                Button("Reset to defaults", id="reset"),
                Button("Cancel", id="cancel"),
                id="filter-buttons",
            ),
        )

    # -- Form composition ---------------------------------------------------

    def _criterion_rows(self) -> Iterable[Widget]:
        """Yield one row per criterion. Disabled criteria show their default."""
        s = self._screen
        yield self._row(
            "rev-growth",
            "Revenue growth",
            "≥",
            s.min_revenue_growth_pct,
            default=15.0,
            unit="%",
        )
        yield self._row(
            "gross-margin",
            "Gross margin",
            "≥",
            s.min_gross_margin_pct,
            default=40.0,
            unit="%",
        )
        yield self._row(
            "net-debt",
            "Net debt / EBITDA",
            "≤",
            s.max_net_debt_to_ebitda,
            default=1.0,
            unit="x",
        )
        yield self._row(
            "mkt-cap",
            "Market cap",
            "≥",
            None if s.min_market_cap_usd is None else s.min_market_cap_usd / 1e9,
            default=1.0,
            unit="$B",
        )
        yield self._row(
            "fcf-yield",
            "FCF yield",
            "≥",
            s.min_fcf_yield_pct,
            default=0.0,
            unit="%",
        )
        # Risk-tolerance ceiling. The displayed default of 60 is the band
        # transition between moderate and high risk — a sensible starting
        # point for "filter out the riskiest candidates without being
        # ultra-conservative".
        yield self._row(
            "risk",
            "Risk score",
            "≤",
            float(s.max_risk_score) if s.max_risk_score is not None else None,
            default=60.0,
            unit="",
        )
        # One Switch + Label per verdict, stacked top-down (best → worst) so
        # disabling REJECT (a common move) is the bottom toggle and the
        # alignment with the criterion rows stays consistent.
        yield Static("Verdicts (post-scoring filter):", id="verdict-section-header")
        for v in reversed(list(Verdict)):
            yield self._verdict_row(v)

        # Sector section is only rendered when the universe actually contains
        # sectored instruments — keeps the modal compact for stub-only datasets.
        if self._known_sectors:
            yield Static("Sectors:", id="sector-section-header")
            for sector in self._known_sectors:
                yield self._sector_row(sector)

    def _verdict_row(self, v: Verdict) -> Widget:
        """Build one Switch + Label row for a single verdict level."""
        active = self._screen.verdicts
        slug = f"verdict-{v.value.lower()}"
        return Horizontal(
            Switch(value=active is None or v in active, id=f"toggle-{slug}"),
            Label(v.value, classes="field-label"),
            classes="filter-row",
        )

    def _sector_row(self, sector: str) -> Widget:
        """Build one Switch + Label row for a single sector."""
        active = self._screen.sectors
        return Horizontal(
            Switch(
                value=active is None or sector in active,
                id=_sector_toggle_id(sector),
            ),
            Label(sector, classes="field-label"),
            classes="filter-row",
        )

    def _row(
        self,
        slug: str,
        label: str,
        op: str,
        value: float | None,
        *,
        default: float,
        unit: str,
    ) -> Widget:
        """Build one Switch/Input/Label row.

        ``value`` is the current screen's threshold (or ``None`` if disabled).
        ``default`` is what the input shows when disabled — gives the user a
        sensible value to enable without retyping.
        """
        return Horizontal(
            Switch(value=value is not None, id=f"toggle-{slug}"),
            Label(label, classes="field-label"),
            Label(op, classes="op"),
            Input(
                value=str(value if value is not None else default),
                id=f"input-{slug}",
                type="number",
            ),
            Label(unit, classes="unit"),
            classes="filter-row",
        )

    # -- Actions ------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dispatch Apply/Reset/Cancel buttons."""
        if event.button.id == "apply":
            self.dismiss(self._build_screen())
        elif event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "reset":
            from openbourse.screening import BUILTIN_SCREENS

            # If this is a built-in screen, snap back to its canonical
            # definition; otherwise just dismiss with the current state.
            default = BUILTIN_SCREENS.get(self._screen.name)
            self.dismiss(default if default is not None else self._screen)

    def action_cancel(self) -> None:
        """Escape key dismisses without applying."""
        self.dismiss(None)

    # -- State extraction ---------------------------------------------------

    def _build_screen(self) -> ScreenDefinition:
        """Read every Switch + Input and produce a new ScreenDefinition."""
        risk = self._read_field("risk")
        return replace(
            self._screen,
            min_revenue_growth_pct=self._read_field("rev-growth"),
            min_gross_margin_pct=self._read_field("gross-margin"),
            max_net_debt_to_ebitda=self._read_field("net-debt"),
            min_market_cap_usd=self._read_field("mkt-cap", multiplier=1e9),
            min_fcf_yield_pct=self._read_field("fcf-yield"),
            # Risk score is integer-typed in the domain model; round here
            # rather than push float-handling into the screening service.
            max_risk_score=round(risk) if risk is not None else None,
            sectors=self._read_sector_filter(),
            verdicts=self._read_verdict_filter(),
        )

    def _read_sector_filter(self) -> frozenset[str] | None:
        """Read the dynamic sector switches; ``None`` when all are on or none exist.

        With no known sectors there's nothing to filter, so we mirror the
        unset state. Same collapse-to-None rule applies as for verdicts: if
        every available sector is enabled, the filter is effectively off.
        """
        if not self._known_sectors:
            return None
        selected: set[str] = set()
        for sector in self._known_sectors:
            switch = self.query_one(f"#{_sector_toggle_id(sector)}", Switch)
            if switch.value:
                selected.add(sector)
        if len(selected) == len(self._known_sectors):
            return None
        return frozenset(selected)

    def _read_verdict_filter(self) -> frozenset[Verdict] | None:
        """Read the four verdict switches; return ``None`` when all are on.

        Collapsing the all-on case to ``None`` keeps the filter line in the
        screen-meta strip clean: no point showing "verdict ∈ {all four}".
        """
        selected: set[Verdict] = set()
        for v in Verdict:
            slug = f"toggle-verdict-{v.value.lower()}"
            if self.query_one(f"#{slug}", Switch).value:
                selected.add(v)
        if len(selected) == len(Verdict):
            return None
        return frozenset(selected)

    def _read_field(self, slug: str, *, multiplier: float = 1.0) -> float | None:
        """Return the configured value, or ``None`` when the toggle is off.

        Bad input (e.g. empty string) yields ``None`` rather than crashing —
        we treat it as "leave that filter disabled" so a typo doesn't strand
        the user inside the modal.
        """
        toggle = self.query_one(f"#toggle-{slug}", Switch)
        if not toggle.value:
            return None
        input_widget = self.query_one(f"#input-{slug}", Input)
        try:
            return float(input_widget.value) * multiplier
        except (TypeError, ValueError):
            return None
