"""add is_hidden to posts

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-11 22:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts", sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default="false")
    )
    op.alter_column("posts", "is_hidden", server_default=None)


def downgrade() -> None:
    op.drop_column("posts", "is_hidden")
