"""Plain dataclasses representing business objects.

These types are intentionally framework-free: providers, the screening engine,
the database layer, and the TUI all speak to each other through them.
"""

from openbourse.domain.models import (
    AiBrief,
    Candidate,
    ConcernFinding,
    FundamentalsSnapshot,
    Instrument,
    Quote,
    ScreenDefinition,
    ScreenResult,
    Verdict,
)

__all__ = [
    "AiBrief",
    "Candidate",
    "ConcernFinding",
    "FundamentalsSnapshot",
    "Instrument",
    "Quote",
    "ScreenDefinition",
    "ScreenResult",
    "Verdict",
]
