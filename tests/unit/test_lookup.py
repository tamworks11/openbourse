"""Tests for the single-ticker lookup helper."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from openbourse.db.repositories import FundamentalsRepository, InstrumentRepository
from openbourse.domain import Instrument, Verdict
from openbourse.providers.base import Providers
from openbourse.screening import TickerLookupError, lookup_candidate, lookup_with_history


async def test_lookup_known_ticker_returns_candidate(stub_providers: Providers) -> None:
    candidate = await lookup_candidate("CDNS", stub_providers)
    assert candidate.instrument.ticker == "CDNS"
    assert candidate.snapshot.market_cap_usd > 0
    assert isinstance(candidate.verdict, Verdict)
    assert 0 <= candidate.score <= 100


async def test_lookup_is_case_insensitive(stub_providers: Providers) -> None:
    upper = await lookup_candidate("CDNS", stub_providers)
    lower = await lookup_candidate("cdns", stub_providers)
    assert upper.snapshot == lower.snapshot


async def test_lookup_unknown_ticker_raises_lookup_error(stub_providers: Providers) -> None:
    with pytest.raises(TickerLookupError, match="unknown ticker"):
        await lookup_candidate("ZZZZ", stub_providers)


async def test_lookup_blank_ticker_raises_lookup_error(stub_providers: Providers) -> None:
    with pytest.raises(TickerLookupError, match="ticker is required"):
        await lookup_candidate("   ", stub_providers)


async def test_lookup_uses_db_metadata_when_session_provided(
    db_session: AsyncSession, stub_providers: Providers
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

    candidate = await lookup_candidate("CDNS", stub_providers, session=db_session)
    assert candidate.instrument.name == "Cadence Design Systems"
    assert candidate.instrument.sector == "Technology"
    assert candidate.instrument.cik == "0000813672"


async def test_lookup_falls_back_to_minimal_instrument_when_db_empty(
    db_session: AsyncSession, stub_providers: Providers
) -> None:
    candidate = await lookup_candidate("CDNS", stub_providers, session=db_session)
    assert candidate.instrument.ticker == "CDNS"
    assert candidate.instrument.name == "CDNS"  # ticker echoed when DB has no row
    assert candidate.instrument.cik is None


# --- lookup_with_history -----------------------------------------------------


async def test_lookup_with_history_returns_candidate_and_history(
    stub_providers: Providers,
) -> None:
    candidate, history = await lookup_with_history("CDNS", stub_providers, limit=8)
    assert candidate.instrument.ticker == "CDNS"
    assert len(history) >= 2
    assert history[0].as_of < history[-1].as_of


async def test_lookup_with_history_raises_for_unknown(
    db_session: AsyncSession, stub_providers: Providers
) -> None:
    with pytest.raises(TickerLookupError):
        await lookup_with_history("ZZZZ", stub_providers, session=db_session)


async def test_lookup_with_history_persists_to_session(
    db_session: AsyncSession, stub_providers: Providers
) -> None:
    candidate, history = await lookup_with_history(
        "CDNS", stub_providers, session=db_session, limit=8
    )
    assert candidate.instrument.ticker == "CDNS"
    assert history

    fund_repo = FundamentalsRepository(db_session)
    persisted = await fund_repo.history_for_ticker("CDNS")
    assert len(persisted) == len(history)
    assert {s.as_of for s in persisted} == {s.as_of for s in history}
    found = await fund_repo.latest_for_all()
    assert any(inst.ticker == "CDNS" for inst, _ in found)
