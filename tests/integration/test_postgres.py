"""Integration tests requiring a running PostgreSQL.

Run with::

    pytest -m integration

The connection URL comes from ``OPENBOURSE_TEST_DATABASE_URL``. The compose
service in the repo root works out of the box.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from openbourse.db.engine import create_engine_from_url
from openbourse.db.models import Base
from openbourse.db.repositories import InstrumentRepository
from openbourse.domain import Instrument

pytestmark = pytest.mark.integration

PG_URL = os.environ.get(
    "OPENBOURSE_TEST_DATABASE_URL",
    "postgresql+asyncpg://openbourse:openbourse@localhost:5432/openbourse_test",
)


@pytest.fixture
async def pg_session():
    engine = create_engine_from_url(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def test_round_trip_against_real_postgres(pg_session) -> None:
    repo = InstrumentRepository(pg_session)
    await repo.upsert(Instrument(ticker="CDNS", name="Cadence"))
    await pg_session.commit()
    found = await repo.get_by_ticker("CDNS")
    assert found is not None
    assert found.ticker == "CDNS"
