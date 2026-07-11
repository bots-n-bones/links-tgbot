"""add post embedding and qa_logs.matched_post_ids

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-11 22:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("embedding", Vector(1536), nullable=True))
    op.add_column("qa_logs", sa.Column("matched_post_ids", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("qa_logs", "matched_post_ids")
    op.drop_column("posts", "embedding")
