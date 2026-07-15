"""add workspace_id to invites (backfilled to the default workspace)

Revision ID: d3e4f5a6b7c8
Revises: c1d2e3f4a5b6
Create Date: 2026-07-13 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invites", sa.Column("workspace_id", sa.Integer(), nullable=True))

    bind = op.get_bind()
    default_workspace_id = bind.execute(
        sa.text("SELECT id FROM workspaces ORDER BY id LIMIT 1")
    ).scalar_one_or_none()
    if default_workspace_id is not None:
        bind.execute(
            sa.text("UPDATE invites SET workspace_id = :wid WHERE workspace_id IS NULL"),
            {"wid": default_workspace_id},
        )

    op.alter_column("invites", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_invites_workspace_id", "invites", "workspaces", ["workspace_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_invites_workspace_id", "invites", type_="foreignkey")
    op.drop_column("invites", "workspace_id")
