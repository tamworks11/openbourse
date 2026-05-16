"""add pe_ratio_ttm column to fundamentals_snapshots

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-16 13:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, no server default — a NULL means the provider had no usable
    # trailing P/E (missing or non-positive earnings). Existing rows read
    # back as NULL; re-running the universe ingest populates real values.
    op.add_column(
        "fundamentals_snapshots",
        sa.Column("pe_ratio_ttm", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fundamentals_snapshots", "pe_ratio_ttm")
