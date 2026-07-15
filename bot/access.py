"""Whitelist + инвайт-коды для личных сообщений (F-44). В группах не
применяется — чат уже доверенный, добавлен админом вручную (см. решение №1
в плане). Whitelist держится в двух местах: статический ALLOWED_USER_IDS в
.env (владелец бота, бутстрап) и таблица authorized_users в БД (все, кто
погасил инвайт-код) — так новых пользователей можно добавлять без
редактирования .env и перезапуска бота."""

import secrets
import string
from datetime import UTC, datetime

from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from db.models import AuthorizedUser, Invite, User, WorkspaceMember, WorkspaceRole
from db.session import get_sessionmaker
from shared.config import get_settings

NO_ACCESS_TEXT = "Нет доступа. Если у вас есть инвайт-код — отправьте его следующим сообщением."
INVITE_REDEEMED_TEXT = "Код принят, доступ открыт! Наберите /help, чтобы увидеть список команд."
INVITE_INVALID_TEXT = "Такой код не найден или уже использован. Уточните у того, кто вас пригласил."

_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 8


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def _is_statically_whitelisted(user_id: int) -> bool:
    settings = get_settings()
    return user_id == settings.admin_user_id_int or user_id in settings.allowed_user_id_list


def looks_like_invite_code(text: str) -> bool:
    stripped = text.strip().upper()
    return 4 <= len(stripped) <= 16 and all(c in _CODE_ALPHABET for c in stripped)


async def is_whitelisted(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if _is_statically_whitelisted(user_id):
        return True
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = await session.get(AuthorizedUser, user_id)
    return row is not None


async def require_whitelisted(message: Message) -> bool:
    """True если доступ разрешён; иначе отвечает подсказкой про инвайт-код и возвращает False."""
    user_id = message.from_user.id if message.from_user else None
    if await is_whitelisted(user_id):
        return True
    await message.answer(NO_ACCESS_TEXT)
    return False


async def require_authorized(message: Message) -> bool:
    """Как require_whitelisted, но пропускает проверку в группах — там доступ
    уже ограничен на уровне списка участников чата (решение №1 в плане),
    команды в группе доступны всем."""
    if message.chat.type != "private":
        return True
    return await require_whitelisted(message)


async def require_authorized_callback(callback: CallbackQuery) -> bool:
    """Для кнопок: callback.message.from_user — это БОТ (автор сообщения с
    кнопкой), а не нажавший её человек — реальный пользователь только в
    callback.from_user. Использовать require_authorized(callback.message)
    здесь всегда проверяло бы whitelist для бота и отказывало всем."""
    chat = callback.message.chat if callback.message else None
    if chat is not None and chat.type != "private":
        return True
    if await is_whitelisted(callback.from_user.id):
        return True
    if callback.message:
        await callback.message.answer(NO_ACCESS_TEXT)
    return False


async def redeem_invite(user_id: int, code: str) -> bool:
    """Пытается погасить инвайт-код и выдать доступ. True при успехе.

    Заводит WorkspaceMember в workspace инвайта (личный кабинет) — и
    AuthorizedUser для обратной совместимости с is_whitelisted до волны,
    где resolve_workspace/whitelist переезжает целиком на WorkspaceMember."""
    normalized = code.strip().upper()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        invite = await session.scalar(
            select(Invite).where(Invite.code == normalized, Invite.redeemed_by.is_(None))
        )
        if invite is None:
            return False
        invite.redeemed_by = user_id
        invite.redeemed_at = datetime.now(UTC)
        session.add(AuthorizedUser(telegram_id=user_id, invite_code=normalized))

        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        if user is None:
            user = User(telegram_id=user_id)
            session.add(user)
            await session.flush()
        existing_membership = await session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == invite.workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        )
        if existing_membership is None:
            session.add(WorkspaceMember(workspace_id=invite.workspace_id, user_id=user.id))

        await session.commit()
    return True


async def get_owned_workspace_id(telegram_id: int) -> int | None:
    """Первый workspace, которым владеет этот telegram_id (role=owner).

    Временный однозначный резолвер для /invite, пока волна 5 не научит бота
    полноценно резолвить workspace по чату/отправителю — на MVP у каждого
    юзера ровно один workspace, так что "первый" уже однозначен."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            return None
        membership = await session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.role == WorkspaceRole.owner,
            )
        )
        return membership.workspace_id if membership else None


async def create_invite(created_by: int | None, workspace_id: int) -> str:
    code = _generate_code()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        session.add(Invite(code=code, created_by=created_by, workspace_id=workspace_id))
        await session.commit()
    return code
