"""add catalog_views (сохранённые виды каталога)

Revision ID: e5f6a7b8c9da
Revises: d4e5f6a7b8c9
Create Date: 2026-09-09 21:00:00.000000

Вид — это набор фильтров под именем: «что тестировать», «из каналов»,
«всё про AI». Хранится как JSON параметров, а не как отдельные колонки под
каждый фильтр: набор фильтров каталога будет меняться, и вид не должен
требовать миграции каждый раз.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "e5f6a7b8c9da"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("params_json", JSONB(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("workspace_id", "name", name="uq_catalog_views_workspace_name"),
    )


def downgrade() -> None:
    op.drop_table("catalog_views")
