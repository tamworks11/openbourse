"""Screening domain — criteria, scoring, orchestration."""

from openbourse.screening.criteria import BUILTIN_SCREENS, passes_screen
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
    "Weights",
    "composite_score",
    "passes_screen",
    "verdict_for",
]
