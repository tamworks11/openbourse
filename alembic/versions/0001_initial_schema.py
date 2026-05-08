"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-08 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(16), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sector", sa.String(64)),
        sa.Column("exchange", sa.String(16)),
        sa.Column("cik", sa.String(16)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_instruments_ticker", "instruments", ["ticker"], unique=True)
    op.create_index("ix_instruments_cik", "instruments", ["cik"])

    op.create_table(
        "fundamentals_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("market_cap_usd", sa.Float, nullable=False),
        sa.Column("revenue_growth_pct", sa.Float, nullable=False),
        sa.Column("gross_margin_pct", sa.Float, nullable=False),
        sa.Column("net_debt_to_ebitda", sa.Float, nullable=False),
        sa.Column("fcf_yield_pct", sa.Float, nullable=False),
        sa.Column("revenue_ttm_usd", sa.Float),
        sa.Column("ebitda_ttm_usd", sa.Float),
        sa.UniqueConstraint(
            "instrument_id", "as_of", name="uq_fundamentals_instrument_as_of"
        ),
    )
    op.create_index(
        "ix_fundamentals_snapshots_instrument_id",
        "fundamentals_snapshots",
        ["instrument_id"],
    )

    op.create_table(
        "screens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("criteria", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_screens_name", "screens", ["name"], unique=True)

    op.create_table(
        "screen_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "screen_id",
            sa.Integer,
            sa.ForeignKey("screens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ran_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("universe_size", sa.Integer, nullable=False),
        sa.Column("candidate_count", sa.Integer, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_screen_runs_screen_id", "screen_runs", ["screen_id"])

    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(16), nullable=False, unique=True),
        sa.Column("notes", sa.String(2048)),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_watchlist_entries_ticker", "watchlist_entries", ["ticker"], unique=True
    )

    op.create_table(
        "ai_briefs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "instrument_id",
            sa.Integer,
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(8192), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_ai_briefs_instrument_id", "ai_briefs", ["instrument_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_briefs_instrument_id", table_name="ai_briefs")
    op.drop_table("ai_briefs")
    op.drop_index("ix_watchlist_entries_ticker", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
    op.drop_index("ix_screen_runs_screen_id", table_name="screen_runs")
    op.drop_table("screen_runs")
    op.drop_index("ix_screens_name", table_name="screens")
    op.drop_table("screens")
    op.drop_index(
        "ix_fundamentals_snapshots_instrument_id",
        table_name="fundamentals_snapshots",
    )
    op.drop_table("fundamentals_snapshots")
    op.drop_index("ix_instruments_cik", table_name="instruments")
    op.drop_index("ix_instruments_ticker", table_name="instruments")
    op.drop_table("instruments")
