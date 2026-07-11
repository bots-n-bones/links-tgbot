from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from api.routes.links import query_links
from bot.access import (
    INVITE_INVALID_TEXT,
    INVITE_REDEEMED_TEXT,
    NO_ACCESS_TEXT,
    is_whitelisted,
    looks_like_invite_code,
    redeem_invite,
)
from bot.extractors import extract_urls
from bot.formatting import format_link_list_html, format_qa_reply_html
from bot.ingest import enqueue_processing, entities_to_json, ingest_message
from bot.keyboards import main_menu_keyboard
from bot.states import MenuState
from db.models import SourceType
from db.session import get_sessionmaker
from worker.chat import answer_casually
from worker.rag import answer_question

router = Router(name="private")
router.message.filter(F.chat.type == "private")

HELP_HINT_TEXT = "Не нашёл ссылку. Наберите /help, если нужна подсказка."


async def _handle_pending_menu_state(message: Message, state: FSMContext) -> bool:
    """Обрабатывает текст, введённый в ответ на кнопку Ask/Search (F: кнопки,
    а не команды). True — сообщение обработано в рамках ожидаемого действия."""
    current_state = await state.get_state()
    if current_state is None:
        return False

    text = (message.text or message.caption or "").strip()
    await state.clear()
    if not text:
        return False

    if current_state == MenuState.waiting_for_ask.state:
        result = await answer_question(
            text, user_id=message.from_user.id if message.from_user else None
        )
        await message.answer(
            format_qa_reply_html(result), parse_mode="HTML", reply_markup=main_menu_keyboard()
        )
        return True

    if current_state == MenuState.waiting_for_search.state:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            result = await query_links(session, q=text, sort="priority", page=1, page_size=10)
        if not result.items:
            await message.answer("Ничего не найдено.", reply_markup=main_menu_keyboard())
        else:
            await message.answer(
                format_link_list_html(result.items),
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
        return True

    return False


@router.message()
async def handle_private_message(message: Message, state: FSMContext) -> None:
    """Роутинг по §6.4: URL → добавление; команды перехватываются
    bot/handlers/commands.py раньше (регистрируется первым); текст без
    URL → Q&A (RAG); иное (нет текста вовсе) → подсказка."""
    user_id = message.from_user.id if message.from_user else None
    if not await is_whitelisted(user_id):
        text = (message.text or message.caption or "").strip()
        if user_id is not None and text and looks_like_invite_code(text):
            if await redeem_invite(user_id, text):
                await message.answer(INVITE_REDEEMED_TEXT)
            else:
                await message.answer(INVITE_INVALID_TEXT)
        else:
            await message.answer(NO_ACCESS_TEXT)
        return

    if await _handle_pending_menu_state(message, state):
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
        # Свободный текст (не /ask) — просто ответ на сообщение, без поиска по
        # базе и без списка источников (это отдельно доступно через /ask).
        text = message.text or message.caption
        answer = await answer_casually(text)
        await message.answer(answer)
        return

    await message.answer(HELP_HINT_TEXT)
