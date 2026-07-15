"""FastAPI-зависимости для личного кабинета (см. план "Личный кабинет +
workspace"). Первый Depends()-паттерн в кодовой базе — до этого ни один
роут не знал, кто сделал запрос (см. api/main.py)."""

from fastapi import Request
from sqlalchemy import select

from db.models import User, WorkspaceMember
from db.session import get_sessionmaker


async def get_current_user(request: Request) -> User | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        return await session.get(User, user_id)


async def get_current_workspace_id(request: Request) -> int | None:
    """workspace_id залогиненного пользователя, или None если не залогинен
    либо ещё не состоит ни в одном workspace (см. волна 4 плана "Личный
    кабинет + workspace" — каждый роут дашборда скоупит данные по этому
    workspace_id вместо показа общей базы всем)."""
    user = await get_current_user(request)
    if user is None:
        return None
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
        )
    return membership.workspace_id if membership else None
