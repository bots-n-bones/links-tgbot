"""add manual priority and is_tested to links

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-12 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    manual_priority_enum = sa.Enum("low", "normal", "high", name="manual_priority")
    manual_priority_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "links",
        sa.Column(
            "manual_priority",
            manual_priority_enum,
            nullable=False,
            server_default="normal",
        ),
    )
    op.alter_column("links", "manual_priority", server_default=None)
    op.add_column(
        "links", sa.Column("is_tested", sa.Boolean(), nullable=False, server_default="false")
    )
    op.alter_column("links", "is_tested", server_default=None)


def downgrade() -> None:
    op.drop_column("links", "is_tested")
    op.drop_column("links", "manual_priority")
    sa.Enum(name="manual_priority").drop(op.get_bind(), checkfirst=True)
