"""add click_count to links

Revision ID: ab72edf707d5
Revises: 2a415bdbdf9f
Create Date: 2026-07-10 18:06:10.738850

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab72edf707d5"
down_revision: str | None = "2a415bdbdf9f"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "links",
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("links", "click_count")
