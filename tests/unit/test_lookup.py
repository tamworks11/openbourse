"""Tests for the single-ticker lookup helper."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from openbourse.db.repositories import InstrumentRepository
from openbourse.domain import Instrument, Verdict
from openbourse.providers import build_providers
from openbourse.screening import TickerLookupError, lookup_candidate


async def test_lookup_known_ticker_returns_candidate() -> None:
    providers = build_providers()  # use_stubs=True default
    candidate = await lookup_candidate("CDNS", providers)
    assert candidate.instrument.ticker == "CDNS"
    assert candidate.snapshot.market_cap_usd > 0
    assert isinstance(candidate.verdict, Verdict)
    assert 0 <= candidate.score <= 100


async def test_lookup_is_case_insensitive() -> None:
    providers = build_providers()
    upper = await lookup_candidate("CDNS", providers)
    lower = await lookup_candidate("cdns", providers)
    assert upper.snapshot == lower.snapshot


async def test_lookup_unknown_ticker_raises_lookup_error() -> None:
    providers = build_providers()
    with pytest.raises(TickerLookupError, match="unknown ticker"):
        await lookup_candidate("ZZZZ", providers)


async def test_lookup_blank_ticker_raises_lookup_error() -> None:
    providers = build_providers()
    with pytest.raises(TickerLookupError, match="ticker is required"):
        await lookup_candidate("   ", providers)


async def test_lookup_uses_db_metadata_when_session_provided(
    db_session: AsyncSession,
) -> None:
    repo = InstrumentRepository(db_session)
    await repo.upsert(
        Instrument(
            ticker="CDNS",
            name="Cadence Design Systems",
            sector="Technology",
            cik="0000813672",
        )
    )
    await db_session.commit()

    providers = build_providers()
    candidate = await lookup_candidate("CDNS", providers, session=db_session)
    assert candidate.instrument.name == "Cadence Design Systems"
    assert candidate.instrument.sector == "Technology"
    assert candidate.instrument.cik == "0000813672"


async def test_lookup_falls_back_to_minimal_instrument_when_db_empty(
    db_session: AsyncSession,
) -> None:
    providers = build_providers()
    candidate = await lookup_candidate("CDNS", providers, session=db_session)
    assert candidate.instrument.ticker == "CDNS"
    assert candidate.instrument.name == "CDNS"  # ticker echoed when DB has no row
    assert candidate.instrument.cik is None
