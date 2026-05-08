"""SQLAlchemy 2.0 declarative models.

Each ``*Row`` class is a thin persistence record. Conversion to and from the
framework-free :mod:`openbourse.domain` dataclasses lives in the repositories.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Common declarative base."""


class InstrumentRow(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(64))
    exchange: Mapped[str | None] = mapped_column(String(16))
    cik: Mapped[str | None] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    snapshots: Mapped[list[FundamentalsRow]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )
    briefs: Mapped[list[AiBriefRow]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )


class FundamentalsRow(Base):
    __tablename__ = "fundamentals_snapshots"
    __table_args__ = (
        UniqueConstraint("instrument_id", "as_of", name="uq_fundamentals_instrument_as_of"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    market_cap_usd: Mapped[float] = mapped_column(Float, nullable=False)
    revenue_growth_pct: Mapped[float] = mapped_column(Float, nullable=False)
    gross_margin_pct: Mapped[float] = mapped_column(Float, nullable=False)
    net_debt_to_ebitda: Mapped[float] = mapped_column(Float, nullable=False)
    fcf_yield_pct: Mapped[float] = mapped_column(Float, nullable=False)
    revenue_ttm_usd: Mapped[float | None] = mapped_column(Float)
    ebitda_ttm_usd: Mapped[float | None] = mapped_column(Float)

    instrument: Mapped[InstrumentRow] = relationship(back_populates="snapshots")


class ScreenRow(Base):
    __tablename__ = "screens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    criteria: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    runs: Mapped[list[ScreenRunRow]] = relationship(
        back_populates="screen", cascade="all, delete-orphan"
    )


class ScreenRunRow(Base):
    __tablename__ = "screen_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    screen_id: Mapped[int] = mapped_column(
        ForeignKey("screens.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    universe_size: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    screen: Mapped[ScreenRow] = relationship(back_populates="runs")


class WatchlistRow(Base):
    __tablename__ = "watchlist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(String(2048))
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiBriefRow(Base):
    __tablename__ = "ai_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(8192), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)

    instrument: Mapped[InstrumentRow] = relationship(back_populates="briefs")
