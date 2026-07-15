"""add workspace, user, workspace_member models + backfill from authorized_users

Revision ID: c1d2e3f4a5b6
Revises: b4c5d6e7f8a9
Create Date: 2026-07-13 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    workspace_role = sa.Enum("owner", "member", name="workspace_role")

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("plan", sa.String(length=20), nullable=False, server_default="free"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id", sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("role", workspace_role, nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )

    # Бэкфилл: один Workspace на всё, что уже накоплено + один User/WorkspaceMember
    # на каждого текущего authorized_users. ADMIN_USER_ID (см. shared/config.py)
    # получает role=owner, остальные — member. Читаем ADMIN_USER_ID напрямую из
    # окружения (не через get_settings(), чтобы не тащить app-импорты в миграцию).
    import os

    bind = op.get_bind()
    admin_user_id_raw = os.environ.get("ADMIN_USER_ID", "").strip()
    admin_user_id = int(admin_user_id_raw) if admin_user_id_raw else None

    workspace_id = bind.execute(
        sa.text("INSERT INTO workspaces (name, plan) VALUES ('Default', 'free') RETURNING id")
    ).scalar_one()

    existing_telegram_ids = {
        row[0]
        for row in bind.execute(sa.text("SELECT telegram_id FROM authorized_users")).fetchall()
    }
    if admin_user_id is not None:
        existing_telegram_ids.add(admin_user_id)

    for telegram_id in existing_telegram_ids:
        user_id = bind.execute(
            sa.text("INSERT INTO users (telegram_id) VALUES (:tid) RETURNING id"),
            {"tid": telegram_id},
        ).scalar_one()
        role = "owner" if telegram_id == admin_user_id else "member"
        bind.execute(
            sa.text(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES (:wid, :uid, :role)"
            ),
            {"wid": workspace_id, "uid": user_id, "role": role},
        )


def downgrade() -> None:
    op.drop_table("workspace_members")
    op.drop_table("users")
    op.drop_table("workspaces")
    sa.Enum(name="workspace_role").drop(op.get_bind(), checkfirst=True)
