"""Whitelist + инвайт-коды для личных сообщений (F-44). В группах не
применяется — чат уже доверенный, добавлен админом вручную (см. решение №1
в плане). Whitelist держится в двух местах: статический ALLOWED_USER_IDS в
.env (владелец бота, бутстрап) и таблица authorized_users в БД (все, кто
погасил инвайт-код) — так новых пользователей можно добавлять без
редактирования .env и перезапуска бота."""

import secrets
import string
from datetime import UTC, datetime

from aiogram.types import Message
from sqlalchemy import select

from db.models import AuthorizedUser, Invite
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


async def redeem_invite(user_id: int, code: str) -> bool:
    """Пытается погасить инвайт-код и выдать доступ. True при успехе."""
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
        await session.commit()
    return True


async def create_invite(created_by: int | None) -> str:
    code = _generate_code()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        session.add(Invite(code=code, created_by=created_by))
        await session.commit()
    return code
