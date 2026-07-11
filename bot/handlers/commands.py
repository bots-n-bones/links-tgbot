from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import func, select

from api.routes.links import query_links
from bot.access import create_invite, require_whitelisted
from bot.formatting import format_qa_reply
from db.models import Collection, Link, LinkSource, LinkTag, Tag
from db.session import get_sessionmaker
from shared.config import get_settings
from worker.rag import answer_question

router = Router(name="commands")
router.message.filter(F.chat.type == "private")

START_TEXT = (
    "Привет! Я собираю полезные ссылки команды.\n\n"
    "Пришлите мне ссылку (можно с комментарием, можно пересланное сообщение) — "
    "я добавлю её в базу.\n"
    "Наберите /help, чтобы увидеть список команд."
)

HELP_TEXT = (
    "Доступные команды:\n"
    "/ask <вопрос> — задать вопрос базе ссылок\n"
    "/search <тема> — краткий список ссылок по теме\n"
    "/digest — последняя тематическая подборка\n"
    "/stats — статистика по базе\n\n"
    "Также можно просто прислать ссылку — я её обработаю."
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not await require_whitelisted(message):
        return
    await message.answer(START_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if not await require_whitelisted(message):
        return
    await message.answer(HELP_TEXT)


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
    if not await require_whitelisted(message):
        return
    question = (command.args or "").strip()
    if not question:
        await message.answer("Использование: /ask <вопрос>")
        return
    result = await answer_question(
        question, user_id=message.from_user.id if message.from_user else None
    )
    await message.answer(format_qa_reply(result))


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject) -> None:
    """F-search: краткий список ссылок по теме, без LLM-прозы (в отличие от /ask)."""
    if not await require_whitelisted(message):
        return
    topic = (command.args or "").strip()
    if not topic:
        await message.answer("Использование: /search <тема>")
        return

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(session, q=topic, sort="priority", page=1, page_size=10)

    if not result.items:
        await message.answer("Ничего не найдено.")
        return

    lines = [f"- {link.title or link.url} ({link.url})" for link in result.items]
    await message.answer("\n".join(lines))


@router.message(Command("digest"))
async def cmd_digest(message: Message) -> None:
    if not await require_whitelisted(message):
        return

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        collection = await session.scalar(
            select(Collection).order_by(Collection.created_at.desc()).limit(1)
        )

    if collection is None:
        await message.answer("Подборок пока нет — первая соберётся автоматически по расписанию.")
        return

    text = f"{collection.title}\n\n{collection.summary_md}"
    await message.answer(text[:4000])


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not await require_whitelisted(message):
        return

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
    await message.answer("\n".join(lines))
