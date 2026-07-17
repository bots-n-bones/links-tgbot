"""Личный кабинет — PATCH/POST-эндпоинты (см. план "Личный кабинет +
workspace", волна 3). HTML-страница /account — в api/main.py, по
конвенции проекта (HTML в main.py, JSON/PATCH — в routes/*.py)."""

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import get_current_user
from bot.access import create_invite
from bot.keyboards import invite_decision_keyboard
from db.models import ChannelWatch, Invite, WorkspaceMember, WorkspaceRole
from db.session import get_sessionmaker
from shared.config import get_settings
from shared.telegram_throttle import send_message_throttled
from worker.channel_scraper import normalize_channel_username

router = APIRouter(prefix="/api/account", tags=["account"])


async def _owned_workspace_id(user) -> int:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id == user.id, WorkspaceMember.role == WorkspaceRole.owner
            )
        )
        if membership is None:
            raise HTTPException(status_code=403, detail="Only workspace owners can invite")
        return membership.workspace_id


@router.post("/invites")
async def create_account_invite(request: Request):
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    workspace_id = await _owned_workspace_id(user)
    code = await create_invite(created_by=user.telegram_id, workspace_id=workspace_id)
    return {"code": code}


class InviteByTelegramIdIn(BaseModel):
    target_telegram_id: int


@router.post("/invites/by-telegram-id")
async def create_account_invite_by_telegram_id(request: Request, body: InviteByTelegramIdIn):
    """Адресный DM-инвайт (личный кабинет v2, волна 5) — если бот не может
    написать первым (юзер никогда его не открывал), тихий fallback на
    обычный код, который owner форвардит вручную."""
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    workspace_id = await _owned_workspace_id(user)
    code = await create_invite(
        created_by=user.telegram_id,
        workspace_id=workspace_id,
        target_telegram_id=body.target_telegram_id,
    )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        invite_id = await session.scalar(select(Invite.id).where(Invite.code == code))

    settings = get_settings()
    if not settings.bot_token:
        return {"fallback": True, "code": code}

    bot = Bot(token=settings.bot_token)
    try:
        text = "You've been invited to join a team on Nova-260."
        await send_message_throttled(
            bot,
            body.target_telegram_id,
            text,
            reply_markup=invite_decision_keyboard(invite_id),
        )
        return {"sent": True}
    except (TelegramForbiddenError, TelegramBadRequest):
        # Forbidden — юзер никогда не открывал чат с ботом; BadRequest
        # ("chat not found") — ID не существует/опечатка. Оба случая —
        # тихий fallback на код, а не 500.
        return {"fallback": True, "code": code}
    finally:
        await bot.session.close()


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
