"""add links.reviewed_at (Inbox: разобрано или ещё нет)

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-09-09 19:00:00.000000

Бэкфилла намеренно нет. Соблазн был — проставить reviewed_at всем ссылкам,
которых кто-то касался (tested, приоритет не normal, были клики), чтобы
Inbox не открылся сразу с сотней записей. Но это означало бы записать в
базу разбор, которого не было: до этой миграции признака «разобрано» не
существовало, и восстановить его из косвенных следов нельзя.

Поэтому все существующие ссылки остаются неразобранными, а Inbox прямо
говорит, что в нём лежит в том числе всё, захваченное до появления этого
режима. Обнулить стопку — одно действие «отметить всё разобранным», и это
решение команды, а не миграции.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("links", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("links", sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_links_reviewed_by_user_id", "links", "users", ["reviewed_by_user_id"], ["id"]
    )
    # Inbox — самый частый запрос каталога, и он всегда фильтр по одному
    # workspace плюс reviewed_at IS NULL.
    op.create_index("ix_links_workspace_reviewed_at", "links", ["workspace_id", "reviewed_at"])


def downgrade() -> None:
    op.drop_index("ix_links_workspace_reviewed_at", table_name="links")
    op.drop_constraint("fk_links_reviewed_by_user_id", "links", type_="foreignkey")
    op.drop_column("links", "reviewed_by_user_id")
    op.drop_column("links", "reviewed_at")
