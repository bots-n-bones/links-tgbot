"""scope links/posts/tags/etc by workspace (backfilled to the default workspace)

Revision ID: e5f6a7b8c9d0
Revises: d3e4f5a6b7c8
Create Date: 2026-07-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Таблицы, которые волна 4 плана "Личный кабинет + workspace" переводит на
# per-workspace изоляцию — просто добавляют workspace_id, без изменений
# уникальных constraint'ов.
SIMPLE_TABLES = [
    "research_reports",
    "collections",
    "qa_logs",
    "channel_parse_jobs",
]

# (таблица, старое имя unique-constraint на одну колонку, новое составное имя,
#  колонки нового составного constraint'а)
COMPOSITE_UNIQUE_TABLES = [
    ("links", "url_hash", "uq_links_workspace_url_hash", ["workspace_id", "url_hash"]),
    ("tags", "name", "uq_tags_workspace_name", ["workspace_id", "name"]),
    ("tags", "slug", "uq_tags_workspace_slug", ["workspace_id", "slug"]),
    (
        "tag_synonyms",
        "raw_value",
        "uq_tag_synonyms_workspace_raw_value",
        ["workspace_id", "raw_value"],
    ),
]


def _single_column_unique_constraint_name(bind, table: str, column: str) -> str | None:
    return bind.execute(
        sa.text(
            """
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
            WHERE tc.table_name = :table AND tc.constraint_type = 'UNIQUE' AND ccu.column_name = :column
            """
        ),
        {"table": table, "column": column},
    ).scalar()


def _add_workspace_column(bind, table: str, default_workspace_id: int | None) -> None:
    op.add_column(table, sa.Column("workspace_id", sa.Integer(), nullable=True))
    if default_workspace_id is not None:
        bind.execute(
            sa.text(f"UPDATE {table} SET workspace_id = :wid WHERE workspace_id IS NULL"),
            {"wid": default_workspace_id},
        )
    op.alter_column(table, "workspace_id", nullable=False)
    op.create_foreign_key(f"fk_{table}_workspace_id", table, "workspaces", ["workspace_id"], ["id"])


def upgrade() -> None:
    bind = op.get_bind()
    default_workspace_id = bind.execute(
        sa.text("SELECT id FROM workspaces ORDER BY id LIMIT 1")
    ).scalar_one_or_none()

    for table in SIMPLE_TABLES:
        _add_workspace_column(bind, table, default_workspace_id)

    # raw_messages: составной unique уже (chat_id, message_id) — расширяем до
    # (workspace_id, chat_id, message_id).
    _add_workspace_column(bind, "raw_messages", default_workspace_id)
    op.drop_constraint("uq_raw_messages_chat_message", "raw_messages", type_="unique")
    op.create_unique_constraint(
        "uq_raw_messages_workspace_chat_message",
        "raw_messages",
        ["workspace_id", "chat_id", "message_id"],
    )

    # posts: аналогично raw_messages.
    _add_workspace_column(bind, "posts", default_workspace_id)
    op.drop_constraint("uq_posts_chat_message", "posts", type_="unique")
    op.create_unique_constraint(
        "uq_posts_workspace_chat_message", "posts", ["workspace_id", "chat_id", "message_id"]
    )

    # links/tags/tag_synonyms: единичный unique -> составной (workspace_id, X).
    # Добавляем колонку один раз на таблицу, constraint'ы дропаем/создаём по списку.
    seen_tables = set()
    for table, old_column, new_name, new_columns in COMPOSITE_UNIQUE_TABLES:
        if table not in seen_tables:
            _add_workspace_column(bind, table, default_workspace_id)
            seen_tables.add(table)
        old_name = _single_column_unique_constraint_name(bind, table, old_column)
        if old_name is not None:
            op.drop_constraint(old_name, table, type_="unique")
        op.create_unique_constraint(new_name, table, new_columns)


def downgrade() -> None:
    for table, old_column, new_name, _new_columns in reversed(COMPOSITE_UNIQUE_TABLES):
        op.drop_constraint(new_name, table, type_="unique")
        op.create_unique_constraint(None, table, [old_column])

    for table in {t for t, *_ in COMPOSITE_UNIQUE_TABLES}:
        op.drop_constraint(f"fk_{table}_workspace_id", table, type_="foreignkey")
        op.drop_column(table, "workspace_id")

    op.drop_constraint("uq_posts_workspace_chat_message", "posts", type_="unique")
    op.create_unique_constraint("uq_posts_chat_message", "posts", ["chat_id", "message_id"])
    op.drop_constraint("fk_posts_workspace_id", "posts", type_="foreignkey")
    op.drop_column("posts", "workspace_id")

    op.drop_constraint("uq_raw_messages_workspace_chat_message", "raw_messages", type_="unique")
    op.create_unique_constraint(
        "uq_raw_messages_chat_message", "raw_messages", ["chat_id", "message_id"]
    )
    op.drop_constraint("fk_raw_messages_workspace_id", "raw_messages", type_="foreignkey")
    op.drop_column("raw_messages", "workspace_id")

    for table in SIMPLE_TABLES:
        op.drop_constraint(f"fk_{table}_workspace_id", table, type_="foreignkey")
        op.drop_column(table, "workspace_id")
