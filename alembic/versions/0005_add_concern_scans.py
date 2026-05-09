"""add concern_scans table for caching 10-K filing scan results

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-08 20:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Cache key is (accession_number, concerns_hash). The hash means a
    # change to the user's concern list invalidates only the scans that
    # would actually return different results — no cascading rebuilds.
    op.create_table(
        "concern_scans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("accession_number", sa.String(32), nullable=False),
        sa.Column("concerns_hash", sa.String(64), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "accession_number", "concerns_hash", name="uq_concern_scans_key"
        ),
    )
    op.create_index(
        "ix_concern_scans_accession",
        "concern_scans",
        ["accession_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_concern_scans_accession", table_name="concern_scans")
    op.drop_table("concern_scans")
