"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from openbourse.db.engine import create_engine_from_url
from openbourse.db.models import Base
from openbourse.domain import FundamentalsSnapshot, Instrument
from openbourse.providers.base import Providers
from openbourse.providers.claude import StubBriefProvider
from openbourse.providers.edgar import StubFilingsProvider
from openbourse.providers.fmp import StubFundamentalsProvider
from openbourse.providers.quotes import StubQuoteProvider
from openbourse.providers.scanner import StubConcernScanner


@pytest.fixture
def sample_instrument() -> Instrument:
    return Instrument(
        ticker="CDNS",
        name="Cadence Design Systems",
        sector="Technology",
        exchange="NASDAQ",
        cik="0000813672",
    )


@pytest.fixture
def sample_snapshot() -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        ticker="CDNS",
        as_of=date(2026, 4, 30),
        market_cap_usd=78_200_000_000,
        revenue_growth_pct=18.4,
        gross_margin_pct=89.1,
        net_debt_to_ebitda=0.2,
        fcf_yield_pct=2.8,
    )


@pytest.fixture
def low_quality_snapshot() -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        ticker="F",
        as_of=date(2026, 4, 30),
        market_cap_usd=48_000_000_000,
        revenue_growth_pct=3.1,
        gross_margin_pct=8.5,
        net_debt_to_ebitda=6.4,
        fcf_yield_pct=4.0,
    )


@pytest_asyncio.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine_from_url("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(sqlite_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _force_stub_providers_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every test to use stub providers regardless of the contributor's ``.env``.

    Without this, tests that go through ``build_providers()`` would dispatch
    real HTTP calls when a developer has live FMP/Claude credentials in
    ``.env`` for day-to-day use. The fixture clears the cached settings so
    the new env value takes effect.
    """
    monkeypatch.setenv("OPENBOURSE_USE_STUBS", "true")
    monkeypatch.delenv("OPENBOURSE_FMP_API_KEY", raising=False)
    monkeypatch.delenv("OPENBOURSE_CLAUDE_API_KEY", raising=False)

    from openbourse import config

    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


@pytest.fixture
def stub_providers() -> Providers:
    """A Providers bundle backed by every stub.

    Tests should depend on this rather than calling ``build_providers()``,
    which reads ``OPENBOURSE_*`` env vars and could end up dispatching real
    HTTP calls when a contributor has live credentials in ``.env``.
    """
    return Providers(
        fundamentals=StubFundamentalsProvider(),
        filings=StubFilingsProvider(),
        brief=StubBriefProvider(),
        scanner=StubConcernScanner(),
        quotes=StubQuoteProvider(),
        fundamentals_mode="stub",
        filings_mode="stub",
        brief_mode="stub",
        scanner_mode="stub",
        quotes_mode="stub",
    )
