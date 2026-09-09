"""Разметка ссылки кнопками под ответом бота.

Момент, когда человек кинул ссылку в чат, — единственный, когда он точно
помнит, зачем он это сделал. Дойти до дашборда успевают не всегда, и
запись остаётся неразобранной, а объяснение теряется. Поэтому базовая
разметка — разобрано, проверено, важное, area, скрыть — делается прямо в
чате, одним нажатием.

Теги сюда не вынесены осознанно: их набор произволен и в клавиатуру не
помещается. Area, наоборот, короткий фиксированный список
(worker.llm.AREA_CHOICES), поэтому влезает кнопками.
"""

from datetime import UTC, datetime

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from bot.access import resolve_workspace_id
from bot.keyboards import CB_LINK_PREFIX, link_actions_keyboard, link_area_keyboard, parse_link_cb
from db.models import Link, User
from db.session import get_sessionmaker
from shared.config import get_settings
from worker.llm import AREA_CHOICES

router = Router(name="link_actions")

NOT_FOUND_TEXT = "Ссылка не найдена — возможно, её удалили."


async def _load_owned_link(session, link_id: int, telegram_id: int) -> Link | None:
    """Ссылка, если она в том же workspace, что и нажавший кнопку.

    Callback data приходит от клиента: не проверив workspace, по номеру
    можно было бы разметить чужую запись."""
    workspace_id = await resolve_workspace_id(telegram_id)
    if workspace_id is None:
        return None
    link = await session.get(Link, link_id)
    if link is None or link.workspace_id != workspace_id:
        return None
    return link


@router.callback_query(lambda callback: (callback.data or "").startswith(CB_LINK_PREFIX))
async def handle_link_action(callback: CallbackQuery) -> None:
    parsed = parse_link_cb(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    action, link_id, value = parsed
    telegram_id = callback.from_user.id if callback.from_user else 0

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await _load_owned_link(session, link_id, telegram_id)
        if link is None:
            await callback.answer(NOT_FOUND_TEXT, show_alert=True)
            return

        # Экран выбора area и возврат назад ничего не меняют в записи —
        # это навигация по клавиатуре, а не действие.
        if action == "areas":
            await callback.message.edit_reply_markup(
                reply_markup=link_area_keyboard(link_id, AREA_CHOICES)
            )
            await callback.answer()
            return
        if action == "back":
            await callback.message.edit_reply_markup(
                reply_markup=link_actions_keyboard(link_id, get_settings().dashboard_url)
            )
            await callback.answer()
            return

        user_id = await session.scalar(select(User.id).where(User.telegram_id == telegram_id))

        if action == "reviewed":
            link.reviewed_at = datetime.now(UTC)
            link.reviewed_by_user_id = user_id
            note = "Отмечено разобранным"
        elif action == "tested":
            # Переключатель, а не установка: промахнуться кнопкой в чате
            # легко, и отменить это должно быть так же просто.
            link.is_tested = not link.is_tested
            note = "Отмечено проверенным" if link.is_tested else "Отметка «проверено» снята"
        elif action == "hide":
            link.is_hidden = not link.is_hidden
            note = "Скрыто из каталога" if link.is_hidden else "Возвращено в каталог"
        elif action == "prio":
            from db.models import ManualPriority

            if value not in (p.value for p in ManualPriority):
                await callback.answer()
                return
            # Повторное нажатие «Важное» возвращает обычный приоритет.
            already_high = link.manual_priority == ManualPriority.high
            link.manual_priority = ManualPriority.normal if already_high else ManualPriority(value)
            note = "Обычный приоритет" if already_high else "Помечено важным"
        elif action == "area":
            if value not in AREA_CHOICES:
                await callback.answer()
                return
            link.area = value
            note = f"Area: {value}"
        else:
            await callback.answer()
            return

        await session.commit()

    if action == "area":
        await callback.message.edit_reply_markup(
            reply_markup=link_actions_keyboard(link_id, get_settings().dashboard_url)
        )
    await callback.answer(note)
