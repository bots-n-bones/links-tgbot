"""Whitelist-проверка для личных сообщений (F-44). В группах не применяется —
чат уже доверенный, добавлен админом вручную (см. решение №1 в плане)."""

from aiogram.types import Message

from shared.config import get_settings

NO_ACCESS_TEXT = "Нет доступа."


def is_whitelisted(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return user_id in get_settings().allowed_user_id_list


async def require_whitelisted(message: Message) -> bool:
    """True если доступ разрешён; иначе отвечает 'Нет доступа' и возвращает False."""
    user_id = message.from_user.id if message.from_user else None
    if is_whitelisted(user_id):
        return True
    await message.answer(NO_ACCESS_TEXT)
    return False
