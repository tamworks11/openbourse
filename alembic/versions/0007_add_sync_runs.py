"""add sync_runs table for tracking universe force-syncs

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-16 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One audit row per `bourse universe sync`. The latest `synced_at` is
    # what the TUI status bar and CLI read to show "DB last synced …".
    # `synced_at` carries no server default — the writer always supplies a
    # UTC-aware value so the timestamp is identical on SQLite and Postgres.
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("ticker_count", sa.Integer(), nullable=False),
        sa.Column("ingested", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sync_runs")
