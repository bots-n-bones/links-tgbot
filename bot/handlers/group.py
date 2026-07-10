from aiogram import F, Router
from aiogram.types import Message

from bot.extractors import extract_urls
from bot.ingest import enqueue_processing, entities_to_json, ingest_message
from db.models import SourceType
from db.session import get_sessionmaker

router = Router(name="group")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message()
async def handle_group_message(message: Message) -> None:
    # Whitelist здесь не применяется — чат уже доверенный (решение №1 в плане).
    urls = extract_urls(message)
    if not urls:
        return  # F-01: без ссылки — тихо игнорируем, чтобы не спамить чат

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        raw_message, is_new = await ingest_message(
            session,
            chat_id=message.chat.id,
            message_id=message.message_id,
            sender_id=message.from_user.id if message.from_user else None,
            text=message.text or message.caption,
            entities_json=entities_to_json(message.entities or message.caption_entities),
            source_type=SourceType.group,
        )

    if is_new:
        enqueue_processing(raw_message.id)
