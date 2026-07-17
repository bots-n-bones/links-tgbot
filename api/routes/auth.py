"""Логин через Telegram Login Widget (личный кабинет, см. план "Личный
кабинет + workspace"). HTML-роуты — по конвенции проекта они здесь, а не
в api/main.py, потому что это самостоятельный, изолированный поток (в
отличие от остальных HTML-роутов, которые исторически живут в main.py)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from api.templates_env import templates
from db.models import User
from db.session import get_sessionmaker
from shared.config import get_settings
from shared.telegram_auth import verify_telegram_login

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        request, "login.html", {"bot_username": settings.bot_username}
    )


@router.get("/login/callback")
async def login_callback(request: Request):
    settings = get_settings()
    payload = dict(request.query_params)
    if not verify_telegram_login(payload, settings.bot_token):
        return HTMLResponse("Login verification failed.", status_code=401)

    telegram_id = int(payload["id"])
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            user = User(telegram_id=telegram_id)
            session.add(user)
        user.username = payload.get("username")
        user.full_name = " ".join(
            part for part in [payload.get("first_name"), payload.get("last_name")] if part
        )
        user.avatar_url = payload.get("photo_url")
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    request.session["user_id"] = user_id
    # Кэш имени/аватара в сессии — чтобы шапка (base.html) не делала отдельный
    # DB-запрос на каждый рендер. Имя всегда из Telegram, никнейм больше не
    # редактируется вручную (личный кабинет v2).
    request.session["display_name"] = user.full_name or user.username or str(user.telegram_id)
    request.session["avatar_url"] = user.avatar_url
    return RedirectResponse("/")


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
