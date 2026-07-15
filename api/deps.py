"""FastAPI-зависимости для личного кабинета (см. план "Личный кабинет +
workspace"). Первый Depends()-паттерн в кодовой базе — до этого ни один
роут не знал, кто сделал запрос (см. api/main.py)."""

from fastapi import Request

from db.models import User
from db.session import get_sessionmaker


async def get_current_user(request: Request) -> User | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        return await session.get(User, user_id)
