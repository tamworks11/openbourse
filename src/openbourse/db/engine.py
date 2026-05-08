"""Async engine and session factories.

The engine is created lazily so importing this module never opens a
connection. Tests construct their own engine bound to ``sqlite+aiosqlite``
and pass it through :func:`get_session_factory`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from openbourse.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine_from_url(url: str, *, echo: bool = False) -> AsyncEngine:
    """Construct an :class:`AsyncEngine` from a SQLAlchemy URL.

    SQLite URLs use a static pool so an in-memory database can be shared
    across connections within a single test process.
    """

    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        return create_async_engine(
            url,
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_async_engine(url, echo=echo, future=True, pool_pre_ping=True)


def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it from settings on first use."""

    global _engine
    if _engine is None:
        _engine = create_engine_from_url(get_settings().database_url)
    return _engine


def get_session_factory(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Return (and cache) a session factory bound to ``engine``."""

    global _session_factory
    if engine is not None:
        return async_sessionmaker(engine, expire_on_commit=False)
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """Yield a session that commits on exit, rolls back on exception."""

    factory = factory or get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Tear down the cached engine. Call once on application shutdown."""

    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
