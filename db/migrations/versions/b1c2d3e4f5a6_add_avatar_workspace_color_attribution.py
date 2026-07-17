"""add user avatar, workspace color, link/post attribution, invite target+status

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-07-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column(
        "workspaces", sa.Column("color", sa.String(length=20), server_default="--cyan", nullable=True)
    )

    op.add_column("links", sa.Column("added_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_links_added_by_user_id", "links", "users", ["added_by_user_id"], ["id"]
    )

    op.add_column("posts", sa.Column("added_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_posts_added_by_user_id", "posts", "users", ["added_by_user_id"], ["id"]
    )

    op.add_column("invites", sa.Column("target_telegram_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "invites", sa.Column("status", sa.String(length=12), server_default="pending", nullable=True)
    )
    op.execute("UPDATE invites SET status = 'accepted' WHERE redeemed_at IS NOT NULL")


def downgrade() -> None:
    op.drop_column("invites", "status")
    op.drop_column("invites", "target_telegram_id")

    op.drop_constraint("fk_posts_added_by_user_id", "posts", type_="foreignkey")
    op.drop_column("posts", "added_by_user_id")

    op.drop_constraint("fk_links_added_by_user_id", "links", type_="foreignkey")
    op.drop_column("links", "added_by_user_id")

    op.drop_column("workspaces", "color")
    op.drop_column("users", "avatar_url")
