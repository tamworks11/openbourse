"""add business_summary to instruments

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-08 19:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "instruments",
        sa.Column("business_summary", sa.String(4096), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instruments", "business_summary")
