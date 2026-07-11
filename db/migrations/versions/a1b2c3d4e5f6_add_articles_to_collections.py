"""add articles to collections

Revision ID: a1b2c3d4e5f6
Revises: f3a1c9d0e7b2
Create Date: 2026-07-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f3a1c9d0e7b2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("collections", sa.Column("articles", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("collections", "articles")
