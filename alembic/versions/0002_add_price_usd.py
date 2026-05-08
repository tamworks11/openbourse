"""add price_usd to fundamentals_snapshots

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-08 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fundamentals_snapshots",
        sa.Column("price_usd", sa.Float, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fundamentals_snapshots", "price_usd")
