"""add raw_messages attribution (кто, откуда, в ответ на что, откуда переслано)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-09 20:00:00.000000

LinkSource с самого начала умеет хранить sender_name, chat_title,
reply_to_text и forwarded_from, но пайплайн ссылок их никогда не заполнял:
эти поля писал только захват постов (bot/post_capture.py), а ссылки шли
через raw_messages, где таких колонок не было. В результате у каждой
ссылки в базе автор и чат — NULL, и сказать, кто её принёс, нельзя.

Бэкфилла нет и быть не может: исходные Telegram-сообщения у нас не
хранятся целиком, восстанавливать автора неоткуда. Заполняться будет то,
что придёт после миграции.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("raw_messages", sa.Column("sender_name", sa.Text(), nullable=True))
    op.add_column("raw_messages", sa.Column("chat_title", sa.Text(), nullable=True))
    op.add_column("raw_messages", sa.Column("reply_to_text", sa.Text(), nullable=True))
    op.add_column("raw_messages", sa.Column("forwarded_from", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_messages", "forwarded_from")
    op.drop_column("raw_messages", "reply_to_text")
    op.drop_column("raw_messages", "chat_title")
    op.drop_column("raw_messages", "sender_name")
