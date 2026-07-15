"""add channel_parse_jobs.requested_by_user_id and channel_watches

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-15 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_parse_jobs", sa.Column("requested_by_user_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_channel_parse_jobs_requested_by_user_id",
        "channel_parse_jobs",
        "users",
        ["requested_by_user_id"],
        ["id"],
    )

    op.create_table(
        "channel_watches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel_username", sa.String(length=32), nullable=False),
        sa.Column("notify_on_new_report", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "channel_username", name="uq_channel_watches_user_channel"),
    )


def downgrade() -> None:
    op.drop_table("channel_watches")
    op.drop_constraint(
        "fk_channel_parse_jobs_requested_by_user_id", "channel_parse_jobs", type_="foreignkey"
    )
    op.drop_column("channel_parse_jobs", "requested_by_user_id")
