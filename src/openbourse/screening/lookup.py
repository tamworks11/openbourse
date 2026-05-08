"""Single-ticker lookup: fetch fundamentals, score, return a Candidate.

Used by both the ``bourse lookup`` CLI command and the TUI lookup modal so
the two paths produce identical results from the same inputs.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from openbourse.db.repositories import InstrumentRepository
from openbourse.domain import Candidate, Instrument
from openbourse.providers.base import Providers
from openbourse.screening.scoring import Weights, composite_score, verdict_for


class TickerLookupError(Exception):
    """Raised when a ticker cannot be resolved by the configured fundamentals provider."""


async def lookup_candidate(
    ticker: str,
    providers: Providers,
    *,
    session: AsyncSession | None = None,
    weights: Weights | None = None,
) -> Candidate:
    """Resolve ``ticker`` to a fully-scored :class:`Candidate`.

    The instrument metadata is looked up in the database when ``session`` is
    provided; otherwise a minimal :class:`Instrument` is synthesised from the
    ticker alone. Fundamentals always come from
    ``providers.fundamentals.fetch``.

    Raises :class:`TickerLookupError` if the provider cannot resolve the
    ticker (e.g. unknown symbol, network failure).
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise TickerLookupError("ticker is required")

    instrument: Instrument | None = None
    if session is not None:
        instrument = await InstrumentRepository(session).get_by_ticker(ticker)
    if instrument is None:
        instrument = Instrument(ticker=ticker, name=ticker)

    try:
        snapshot = await providers.fundamentals.fetch(ticker)
    except KeyError as exc:
        raise TickerLookupError(f"unknown ticker: {ticker}") from exc

    score = composite_score(snapshot, weights=weights or Weights())
    return Candidate(
        instrument=instrument,
        snapshot=snapshot,
        score=score,
        verdict=verdict_for(score),
    )
