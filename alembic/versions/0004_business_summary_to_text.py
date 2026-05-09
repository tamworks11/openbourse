"""widen instruments.business_summary to TEXT

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-08 19:50:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # KKR's Yahoo description exceeds 4 kB; rather than picking a bigger
    # arbitrary cap, switch to TEXT (effectively unlimited).
    op.alter_column(
        "instruments",
        "business_summary",
        existing_type=sa.String(4096),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # The downgrade truncates any rows that grew past 4096 chars while the
    # column was TEXT. That's a deliberate trade-off — undoing this
    # migration on a populated DB inherently loses data.
    op.execute(
        "UPDATE instruments SET business_summary = LEFT(business_summary, 4096) "
        "WHERE LENGTH(business_summary) > 4096"
    )
    op.alter_column(
        "instruments",
        "business_summary",
        existing_type=sa.Text(),
        type_=sa.String(4096),
        existing_nullable=True,
    )
