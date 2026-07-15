"""Временный fallback workspace для мест, ещё не умеющих резолвить его
осмысленно (групповые чаты бота — волна 5 добавит WorkspaceChat; scheduled
digest-задачи — пока считаются для одного дефолтного workspace)."""

from sqlalchemy import select

from db.models import Workspace
from db.session import get_sessionmaker


async def get_default_workspace_id() -> int:
    """Самый первый заведённый workspace (тот же "Default", что создаёт
    бэкфилл миграции c1d2e3f4a5b6)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        workspace_id = await session.scalar(select(Workspace.id).order_by(Workspace.id).limit(1))
    if workspace_id is None:
        raise RuntimeError("No workspace exists — run migrations before starting the bot/worker")
    return workspace_id
