"""add priority score to posts

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-11 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts", sa.Column("priority_score", sa.Float(), nullable=False, server_default="0")
    )
    op.alter_column("posts", "priority_score", server_default=None)


def downgrade() -> None:
    op.drop_column("posts", "priority_score")
