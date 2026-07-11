"""add usefulness score to links

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-07-11 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("links", sa.Column("usefulness_score", sa.Float(), nullable=True))
    op.add_column(
        "links", sa.Column("usefulness_breakdown", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("links", "usefulness_breakdown")
    op.drop_column("links", "usefulness_score")
