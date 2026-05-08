"""Orchestration: pull universe + fundamentals, filter, score, sort."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from openbourse.domain import (
    Candidate,
    FundamentalsSnapshot,
    Instrument,
    ScreenDefinition,
    ScreenResult,
)
from openbourse.screening.criteria import passes_screen
from openbourse.screening.scoring import Weights, composite_score, verdict_for


class ScreeningService:
    """Pure, in-memory screen runner.

    The service is intentionally agnostic to where instruments and snapshots
    come from: pass them in, get a :class:`ScreenResult` out. The CLI and TUI
    each compose this with the database and providers as they see fit.
    """

    def __init__(self, *, weights: Weights | None = None) -> None:
        self._weights = weights or Weights()

    def run(
        self,
        screen: ScreenDefinition,
        universe: Iterable[tuple[Instrument, FundamentalsSnapshot]],
    ) -> ScreenResult:
        """Filter ``universe`` by ``screen``, score the survivors, and return them.

        Candidates are returned sorted by score descending; ties break on
        ticker ascending so the order is deterministic across runs.
        """
        rows = list(universe)
        candidates: list[Candidate] = []
        for instrument, snapshot in rows:
            if not passes_screen(snapshot, screen):
                continue
            score = composite_score(snapshot, weights=self._weights)
            candidates.append(
                Candidate(
                    instrument=instrument,
                    snapshot=snapshot,
                    score=score,
                    verdict=verdict_for(score),
                )
            )
        candidates.sort(key=lambda c: (-c.score, c.instrument.ticker))
        return ScreenResult(
            screen=screen,
            ran_at=datetime.now(UTC),
            universe_size=len(rows),
            candidates=tuple(candidates),
        )
