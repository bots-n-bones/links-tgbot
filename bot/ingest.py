"""Общая идемпотентная логика приёма сообщений (F-01/F-02) для group.py и private.py."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RawMessage, SourceType


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
