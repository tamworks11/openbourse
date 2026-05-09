"""Screening domain — criteria, scoring, orchestration."""

from openbourse.screening.criteria import (
    BUILTIN_SCREENS,
    format_active_filters,
    passes_screen,
)
from openbourse.screening.lookup import (
    TickerLookupError,
    lookup_candidate,
    lookup_with_history,
)
from openbourse.screening.scoring import (
    SCORE_MAX,
    VERDICT_THRESHOLDS,
    Weights,
    composite_score,
    verdict_for,
)
from openbourse.screening.service import ScreeningService

__all__ = [
    "BUILTIN_SCREENS",
    "SCORE_MAX",
    "VERDICT_THRESHOLDS",
    "ScreeningService",
    "TickerLookupError",
    "Weights",
    "composite_score",
    "format_active_filters",
    "lookup_candidate",
    "lookup_with_history",
    "passes_screen",
    "verdict_for",
]
