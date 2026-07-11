"""add invites and authorized_users

Revision ID: f3a1c9d0e7b2
Revises: ab72edf707d5
Create Date: 2026-07-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a1c9d0e7b2"
down_revision: str | None = "ab72edf707d5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False, unique=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("redeemed_by", sa.BigInteger(), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "authorized_users",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True),
        sa.Column("invite_code", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("authorized_users")
    op.drop_table("invites")
