from aiogram import F, Router
from aiogram.types import Message

from bot.access import require_whitelisted
from bot.extractors import extract_urls
from bot.formatting import format_qa_reply
from bot.ingest import enqueue_processing, entities_to_json, ingest_message
from db.models import SourceType
from db.session import get_sessionmaker
from worker.rag import answer_question

router = Router(name="private")
router.message.filter(F.chat.type == "private")

HELP_HINT_TEXT = "Не нашёл ссылку. Наберите /help, если нужна подсказка."


@router.message()
async def handle_private_message(message: Message) -> None:
    """Роутинг по §6.4: URL → добавление; команды перехватываются
    bot/handlers/commands.py раньше (регистрируется первым); текст без
    URL → Q&A (RAG); иное (нет текста вовсе) → подсказка."""
    if not await require_whitelisted(message):
        return

    urls = extract_urls(message)
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
                source_type=SourceType.direct,
            )
        if is_new:
            enqueue_processing(raw_message.id)
        # Подтверждение (F-40/41/45) отправит воркер после обработки — Фаза 4.
        return

    if message.text or message.caption:
        question = message.text or message.caption
        result = await answer_question(
            question, user_id=message.from_user.id if message.from_user else None
        )
        await message.answer(format_qa_reply(result))
        return

    await message.answer(HELP_HINT_TEXT)
