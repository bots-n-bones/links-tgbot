"""Личный кабинет — PATCH/POST-эндпоинты (см. план "Личный кабинет +
workspace", волна 3). HTML-страница /account — в api/main.py, по
конвенции проекта (HTML в main.py, JSON/PATCH — в routes/*.py)."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import get_current_user
from bot.access import create_invite
from db.models import ChannelWatch, WorkspaceMember, WorkspaceRole
from db.session import get_sessionmaker
from worker.channel_scraper import normalize_channel_username

router = APIRouter(prefix="/api/account", tags=["account"])


class NicknameIn(BaseModel):
    display_name: str


@router.patch("/nickname")
async def update_nickname(request: Request, body: NicknameIn):
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    display_name = body.display_name.strip()[:100] or None
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        db_user = await session.get(type(user), user.id)
        db_user.display_name = display_name
        await session.commit()

    request.session["display_name"] = (
        display_name or user.full_name or user.username or str(user.telegram_id)
    )
    return {"display_name": request.session["display_name"]}


@router.post("/invites")
async def create_account_invite(request: Request):
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id == user.id, WorkspaceMember.role == WorkspaceRole.owner
            )
        )
        if membership is None:
            raise HTTPException(status_code=403, detail="Only workspace owners can invite")
        workspace_id = membership.workspace_id

    code = await create_invite(created_by=user.telegram_id, workspace_id=workspace_id)
    return {"code": code}


class WatchlistIn(BaseModel):
    channel_username: str


@router.post("/watchlist")
async def add_to_watchlist(request: Request, body: WatchlistIn):
    """Личный watchlist (волна 6) — не привязан к workspace, просто отмечает
    "этот канал интересен именно мне", не дублируя общий каталог job'ов."""
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    username = normalize_channel_username(body.channel_username)
    if username is None:
        raise HTTPException(status_code=422, detail="Invalid channel username")

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        existing = await session.scalar(
            select(ChannelWatch).where(
                ChannelWatch.user_id == user.id, ChannelWatch.channel_username == username
            )
        )
        if existing is None:
            session.add(ChannelWatch(user_id=user.id, channel_username=username))
            await session.commit()
    return {"channel_username": username}


@router.delete("/watchlist/{channel_username}")
async def remove_from_watchlist(request: Request, channel_username: str):
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        existing = await session.scalar(
            select(ChannelWatch).where(
                ChannelWatch.user_id == user.id,
                ChannelWatch.channel_username == channel_username,
            )
        )
        if existing is not None:
            await session.delete(existing)
            await session.commit()
    return {"channel_username": channel_username}
