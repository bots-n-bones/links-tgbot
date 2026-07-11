from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from api.routes.links import query_links
from bot.access import create_invite, require_authorized
from bot.formatting import format_link_list_html, format_qa_reply_html
from bot.keyboards import (
    CB_ASK,
    CB_DAILY_DIGEST,
    CB_HELP,
    CB_SEARCH,
    CB_STATS,
    CB_WEEKLY_DIGEST,
    main_menu_keyboard,
)
from bot.states import MenuState
from db.models import Link, LinkSource, LinkTag, Tag
from db.session import get_sessionmaker
from shared.config import get_settings
from worker.collections import DAILY_DIGEST_THEME, WEEKLY_DIGEST_THEME, format_digest_text
from worker.rag import answer_question

router = Router(name="commands")
router.message.filter(F.chat.type.in_({"private", "group", "supergroup"}))

START_TEXT = (
    "Привет! Я собираю полезные ссылки команды.\n\n"
    "Пришлите мне ссылку (можно с комментарием, можно пересланное сообщение) — "
    "я добавлю её в базу.\n"
    "Пользуйтесь кнопками ниже — они всегда под рукой."
)

HELP_TEXT = (
    "Просто нажимайте на кнопки ниже:\n"
    "📥 Daily digest — сегодняшняя подборка\n"
    "🗓 Weekly digest — подборка за неделю\n"
    "❓ Ask — задать вопрос базе ссылок\n"
    "🔍 Search — краткий список ссылок по теме\n"
    "📊 Stats — статистика по базе\n\n"
    "Также можно просто прислать ссылку — я её обработаю."
)


async def _daily_digest_text() -> str:
    return await _latest_digest_text(DAILY_DIGEST_THEME)


async def _weekly_digest_text() -> str:
    return await _latest_digest_text(WEEKLY_DIGEST_THEME)


async def _latest_digest_text(theme: str) -> str:
    from db.models import Collection

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        collection = await session.scalar(
            select(Collection)
            .where(Collection.theme == theme)
            .order_by(Collection.created_at.desc())
            .limit(1)
        )
    if collection is None:
        return "Подборок пока нет — первая соберётся автоматически по расписанию."
    return format_digest_text(collection)


async def _stats_text() -> str:
    cutoff = datetime.now(UTC) - timedelta(days=7)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        total_links = await session.scalar(select(func.count(Link.id)))
        recent_links = await session.scalar(
            select(func.count(func.distinct(LinkSource.link_id))).where(
                LinkSource.created_at >= cutoff
            )
        )
        top_tags = (
            await session.execute(
                select(Tag.name, func.count(LinkTag.link_id))
                .join(LinkTag, LinkTag.tag_id == Tag.id)
                .group_by(Tag.name)
                .order_by(func.count(LinkTag.link_id).desc())
                .limit(5)
            )
        ).all()

    lines = [f"Всего ссылок в базе: {total_links}", f"За последние 7 дней: {recent_links}"]
    if top_tags:
        lines.append("")
        lines.append("Топ тегов:")
        lines += [f"- {name}: {count}" for name, count in top_tags]
    return "\n".join(lines)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not await require_authorized(message):
        return
    await message.answer(START_TEXT, reply_markup=main_menu_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if not await require_authorized(message):
        return
    await message.answer(HELP_TEXT, reply_markup=main_menu_keyboard())


@router.message(Command("invite"))
async def cmd_invite(message: Message) -> None:
    """Админ-команда: сгенерировать одноразовый инвайт-код для нового
    пользователя (F-44 self-service вместо ручной правки ALLOWED_USER_IDS)."""
    user_id = message.from_user.id if message.from_user else None
    if user_id != get_settings().admin_user_id_int:
        await message.answer("Эта команда доступна только администратору.")
        return
    code = await create_invite(created_by=user_id)
    await message.answer(
        f"Инвайт-код: {code}\n\n"
        "Перешлите его новому пользователю — ему нужно написать боту /start "
        "и в ответ на просьбу ввести этот код сообщением. Код одноразовый."
    )


@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject) -> None:
    if not await require_authorized(message):
        return
    question = (command.args or "").strip()
    if not question:
        await message.answer("Использование: /ask <вопрос>")
        return
    result = await answer_question(
        question, user_id=message.from_user.id if message.from_user else None
    )
    await message.answer(
        format_qa_reply_html(result), parse_mode="HTML", reply_markup=main_menu_keyboard()
    )


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject) -> None:
    """F-search: краткий список ссылок по теме, без LLM-прозы (в отличие от /ask)."""
    if not await require_authorized(message):
        return
    topic = (command.args or "").strip()
    if not topic:
        await message.answer("Использование: /search <тема>")
        return

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(session, q=topic, sort="priority", page=1, page_size=10)

    if not result.items:
        await message.answer("Ничего не найдено.", reply_markup=main_menu_keyboard())
        return

    await message.answer(
        format_link_list_html(result.items), parse_mode="HTML", reply_markup=main_menu_keyboard()
    )


@router.message(Command("daily_digest"))
async def cmd_daily_digest(message: Message) -> None:
    if not await require_authorized(message):
        return
    await message.answer(await _daily_digest_text(), reply_markup=main_menu_keyboard())


@router.message(Command("weekly_digest"))
async def cmd_weekly_digest(message: Message) -> None:
    if not await require_authorized(message):
        return
    await message.answer(await _weekly_digest_text(), reply_markup=main_menu_keyboard())


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not await require_authorized(message):
        return
    await message.answer(await _stats_text(), reply_markup=main_menu_keyboard())


# --- Кнопки главного меню (F: взаимодействие через кнопки, а не команды) ---


@router.callback_query(F.data == CB_DAILY_DIGEST)
async def cb_daily_digest(callback: CallbackQuery) -> None:
    if not callback.message or not await require_authorized(callback.message):
        await callback.answer()
        return
    await callback.message.answer(await _daily_digest_text(), reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == CB_WEEKLY_DIGEST)
async def cb_weekly_digest(callback: CallbackQuery) -> None:
    if not callback.message or not await require_authorized(callback.message):
        await callback.answer()
        return
    await callback.message.answer(await _weekly_digest_text(), reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == CB_STATS)
async def cb_stats(callback: CallbackQuery) -> None:
    if not callback.message or not await require_authorized(callback.message):
        await callback.answer()
        return
    await callback.message.answer(await _stats_text(), reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == CB_HELP)
async def cb_help(callback: CallbackQuery) -> None:
    if not callback.message or not await require_authorized(callback.message):
        await callback.answer()
        return
    await callback.message.answer(HELP_TEXT, reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == CB_ASK)
async def cb_ask_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not await require_authorized(callback.message):
        await callback.answer()
        return
    await state.set_state(MenuState.waiting_for_ask)
    await callback.message.answer("Напишите ваш вопрос следующим сообщением.")
    await callback.answer()


@router.callback_query(F.data == CB_SEARCH)
async def cb_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not await require_authorized(callback.message):
        await callback.answer()
        return
    await state.set_state(MenuState.waiting_for_search)
    await callback.message.answer("Напишите тему для поиска следующим сообщением.")
    await callback.answer()
