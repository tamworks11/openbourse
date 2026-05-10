"""add roic_pct column to fundamentals_snapshots

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-09 22:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Server default of 0.0 means the column can be added to a populated
    # table without a backfill migration. Existing rows read as 0, which
    # the chart treats as "no data" and skips. Re-running the universe
    # ingest with the new code path populates real values per row.
    op.add_column(
        "fundamentals_snapshots",
        sa.Column(
            "roic_pct",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
    )


def downgrade() -> None:
    op.drop_column("fundamentals_snapshots", "roic_pct")
