import re

from aiogram import F, Router
from aiogram.types import Message

from bot.extractors import extract_urls
from bot.ingest import enqueue_processing, entities_to_json, ingest_message
from db.models import SourceType
from db.session import get_sessionmaker
from shared.url_normalizer import is_telegram_link
from worker.rag import answer_question

router = Router(name="group")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


def _strip_mention(text: str, bot_username: str) -> str:
    return re.sub(re.escape(f"@{bot_username}"), "", text, count=1, flags=re.IGNORECASE).strip()


@router.message()
async def handle_group_message(message: Message, bot_username: str = "") -> None:
    # Whitelist здесь не применяется — чат уже доверенный (решение №1 в плане).
    # t.me/telegram.me — ссылки на каналы/чаты (часто просто подпись-атрибуция
    # в пересланных постах), а не на контент — в группах не собираем.
    urls = [u for u in extract_urls(message) if not is_telegram_link(u)]
    if urls:
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
        return

    # Обращение к боту через @username в группе — краткий ответ по базе,
    # без списка источников (как и в личке — F-простой ответ, не подборка).
    text = message.text or message.caption
    if text and bot_username and f"@{bot_username.lower()}" in text.lower():
        question = _strip_mention(text, bot_username) or text
        result = await answer_question(
            question, user_id=message.from_user.id if message.from_user else None
        )
        await message.reply(result.answer)
        return

    # F-01: ни ссылки, ни обращения к боту — тихо игнорируем, чтобы не спамить чат
