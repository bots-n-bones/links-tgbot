"""Общая идемпотентная логика приёма сообщений (F-01/F-02) для group.py и private.py."""

from aiogram.types import Message, MessageOriginChannel, MessageOriginChat, MessageOriginUser
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RawMessage, SourceType


def forwarded_from_name(message: Message) -> str | None:
    """Откуда переслано — канал, чат или человек.

    Скрытый отправитель (MessageOriginHiddenUser) даёт только строку имени,
    поэтому обрабатывается общей веткой ниже."""
    origin = message.forward_origin
    if origin is None:
        return None
    if isinstance(origin, MessageOriginChannel):
        return origin.chat.title or origin.chat.username
    if isinstance(origin, MessageOriginChat):
        return origin.sender_chat.title
    if isinstance(origin, MessageOriginUser):
        return origin.sender_user.full_name
    return getattr(origin, "sender_user_name", None)


def build_source_context(message: Message) -> dict:
    """Кто, откуда и в ответ на что прислал ссылку.

    Эти поля есть у Telegram-сообщения и нужны карточке каталога, чтобы
    показать реплику с автором. Раньше они терялись: raw_messages их не
    хранил, и LinkSource.sender_name/chat_title у ссылок всегда были NULL.
    """
    reply = message.reply_to_message
    return {
        "sender_name": message.from_user.full_name if message.from_user else None,
        # В личке у чата нет названия — там автор и есть весь контекст.
        "chat_title": message.chat.title,
        "reply_to_text": (reply.text or reply.caption) if reply else None,
        "forwarded_from": forwarded_from_name(message),
    }


def entities_to_json(entities: list | None) -> list[dict] | None:
    if not entities:
        return None
    return [
        {
            "type": getattr(e, "type", None),
            "offset": getattr(e, "offset", None),
            "length": getattr(e, "length", None),
            "url": getattr(e, "url", None),
        }
        for e in entities
    ]


async def ingest_message(
    session: AsyncSession,
    *,
    workspace_id: int,
    chat_id: int,
    message_id: int,
    sender_id: int | None,
    text: str | None,
    entities_json: list[dict] | None,
    source_type: SourceType,
    sender_name: str | None = None,
    chat_title: str | None = None,
    reply_to_text: str | None = None,
    forwarded_from: str | None = None,
) -> tuple[RawMessage, bool]:
    """Идемпотентно сохраняет сообщение в raw_messages по
    (workspace_id, chat_id, message_id) (F-02).

    Возвращает (raw_message, is_new).
    """
    stmt = (
        pg_insert(RawMessage)
        .values(
            workspace_id=workspace_id,
            chat_id=chat_id,
            message_id=message_id,
            sender_id=sender_id,
            text=text,
            sender_name=sender_name,
            chat_title=chat_title,
            reply_to_text=reply_to_text,
            forwarded_from=forwarded_from,
            entities_json=entities_json,
            source_type=source_type,
            processed=False,
        )
        .on_conflict_do_nothing(index_elements=["workspace_id", "chat_id", "message_id"])
        .returning(RawMessage)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    await session.commit()
    if row is not None:
        return row, True

    existing = await session.scalar(
        select(RawMessage).where(
            RawMessage.workspace_id == workspace_id,
            RawMessage.chat_id == chat_id,
            RawMessage.message_id == message_id,
        )
    )
    assert existing is not None  # конфликт означает, что строка уже есть
    return existing, False


def enqueue_processing(raw_message_id: int, *, notify: bool = True) -> None:
    """notify=False подавляет обычный ответ бота по ссылке — используется,
    когда то же сообщение одновременно захватывается как пост (см.
    private.py): единое сообщение в этом случае шлёт worker.posts.process_post."""
    from worker.tasks import process_raw_message

    process_raw_message.delay(raw_message_id, notify)


def enqueue_post_processing(payload: dict, *, countdown: int = 20) -> None:
    """countdown: посты со ссылками enqueue'ятся с задержкой, чтобы к моменту
    классификации поста связанная ссылка уже успела обработаться и попасть в
    Post.link_ids (см. worker/posts.py) — не строгая гарантия, лучшее из
    простого."""
    from worker.tasks import process_post_task

    process_post_task.apply_async(args=[payload], countdown=countdown)
