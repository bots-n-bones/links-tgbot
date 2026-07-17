"""Резолюция User.id по telegram_id для атрибуции Link/Post (личный кабинет
v2, статистика "сколько добавил"). Не создаёт User — не у каждого отправителя
есть аккаунт в дашборде, в этом случае атрибуция остаётся NULL."""

from sqlalchemy import select

from db.models import User


async def resolve_user_id_by_telegram(session, telegram_id: int | None) -> int | None:
    if telegram_id is None:
        return None
    return await session.scalar(select(User.id).where(User.telegram_id == telegram_id))
