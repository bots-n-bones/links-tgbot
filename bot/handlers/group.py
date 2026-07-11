import re

from aiogram import F, Router
from aiogram.types import Message

from bot.extractors import extract_urls
from bot.ingest import enqueue_post_processing, enqueue_processing, entities_to_json, ingest_message
from bot.post_capture import build_post_payload
from db.models import SourceType
from db.session import get_sessionmaker
from shared.url_normalizer import is_telegram_link
from worker.chat import answer_casually

router = Router(name="group")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


def _strip_mention(text: str, bot_username: str) -> str:
    return re.sub(re.escape(f"@{bot_username}"), "", text, count=1, flags=re.IGNORECASE).strip()


def _enqueue_post(message: Message, urls: list[str]) -> None:
    payload = build_post_payload(message, urls)
    # Ссылки в посте обрабатываются отдельным быстрым pipeline'ом — даём ему
    # время создать Link до того, как классифицируем пост (см. bot/ingest.py).
    enqueue_post_processing(payload, countdown=20 if urls else 0)


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

    # F: вкладка Posts — сохраняем каждое сообщение в группе, со ссылками или
    # без (пользователь явно попросил без фильтра на "осмысленность").
    if message.text or message.caption or message.photo:
        _enqueue_post(message, urls)

    if urls:
        return

    # Обращение к боту в группе — через @username или ответом (reply) на
    # сообщение бота, чтобы продолжать диалог без повторного упоминания.
    # Просто ответ на реплику, без поиска по базе и без "подборки" (как и в
    # личке — см. bot/handlers/private.py).
    text = message.text or message.caption
    mentioned = bool(text and bot_username and f"@{bot_username.lower()}" in text.lower())
    replied_to_bot = bool(
        bot_username
        and message.reply_to_message
        and message.reply_to_message.from_user
        and (message.reply_to_message.from_user.username or "").lower() == bot_username.lower()
    )
    if text and (mentioned or replied_to_bot):
        question = _strip_mention(text, bot_username) if mentioned else text
        answer = await answer_casually(question)
        await message.reply(answer)
        return

    # F-01: ни ссылки, ни обращения к боту — тихо игнорируем, чтобы не спамить чат
