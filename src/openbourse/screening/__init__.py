"""Screening domain — criteria, scoring, orchestration."""

from openbourse.screening.criteria import BUILTIN_SCREENS, passes_screen
from openbourse.screening.lookup import TickerLookupError, lookup_candidate
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
    "lookup_candidate",
    "passes_screen",
    "verdict_for",
]
