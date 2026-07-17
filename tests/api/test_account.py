import hashlib
import hmac
import time

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from starlette.testclient import TestClient

import api.routes.account as account_module
from api.main import app
from db.models import Invite, User, Workspace, WorkspaceMember, WorkspaceRole
from shared.config import get_settings

TEST_BOT_TOKEN = "999999:test-bot-token-for-account"


def _signed_payload(bot_token: str = TEST_BOT_TOKEN, **overrides) -> dict:
    payload = {
        "id": "777777",
        "first_name": "Grace",
        "username": "grace_hopper",
        "auth_date": str(int(time.time())),
    }
    payload.update(overrides)
    data_check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return payload


def _login(client: TestClient, telegram_id: str) -> None:
    resp = client.get(
        "/login/callback",
        params=_signed_payload(id=telegram_id),
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)


async def test_account_page_redirects_when_not_logged_in(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    with TestClient(app) as client:
        resp = client.get("/account", follow_redirects=False)

    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


async def test_account_page_shows_read_only_telegram_name(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    with TestClient(app) as client:
        _login(client, "777777")
        account_page = client.get("/account")

    assert "Grace" in account_page.text
    assert "@grace_hopper" in account_page.text
    assert "nickname" not in account_page.text.lower()


async def test_nickname_endpoint_removed(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    with TestClient(app) as client:
        _login(client, "777777")
        resp = client.patch("/api/account/nickname", json={"display_name": "Ada"})

    assert resp.status_code == 404


async def test_create_team_for_workspace_less_user(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    with TestClient(app) as client:
        _login(client, "777777")
        resp = client.post("/api/workspace", json={"name": "New Team", "color": "--cyan"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New Team"
    assert body["color"] == "--cyan"

    user = await db_session.scalar(select(User).where(User.telegram_id == 777777))
    membership = await db_session.scalar(
        select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.owner


async def test_rename_team_requires_owner(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    workspace = Workspace(name="Old name", color="--cyan")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)

    user = User(telegram_id=777777)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.member)
    )
    await db_session.commit()

    with TestClient(app) as client:
        _login(client, "777777")
        resp = client.post("/api/workspace", json={"name": "New name", "color": "--green"})

    assert resp.status_code == 403


async def test_rename_team_rejects_invalid_color(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    workspace = Workspace(name="Old name", color="--cyan")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)

    user = User(telegram_id=777777)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()

    with TestClient(app) as client:
        _login(client, "777777")
        resp = client.post("/api/workspace", json={"name": "New name", "color": "#ff00ff"})

    assert resp.status_code == 422


async def test_invite_creation_succeeds_for_owner(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    workspace = Workspace(name="Owner workspace")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)

    user = User(telegram_id=777777)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()

    with TestClient(app) as client:
        _login(client, "777777")
        resp = client.post("/api/account/invites")

    assert resp.status_code == 200
    assert "code" in resp.json()


async def test_invite_creation_returns_403_for_member(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    workspace = Workspace(name="Member workspace")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)

    user = User(telegram_id=777777)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.member)
    )
    await db_session.commit()

    with TestClient(app) as client:
        _login(client, "777777")
        resp = client.post("/api/account/invites")

    assert resp.status_code == 403


async def test_invite_by_telegram_id_sends_dm_with_buttons(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    workspace = Workspace(name="Owner workspace")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)

    user = User(telegram_id=777777)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()

    sent = []

    async def fake_send(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs.get("reply_markup")))

    monkeypatch.setattr(account_module, "send_message_throttled", fake_send)

    with TestClient(app) as client:
        _login(client, "777777")
        resp = client.post("/api/account/invites/by-telegram-id", json={"target_telegram_id": 42})

    assert resp.status_code == 200
    assert resp.json() == {"sent": True}
    assert len(sent) == 1
    assert sent[0][0] == 42
    assert sent[0][2] is not None  # reply_markup с кнопками

    invite = await db_session.scalar(select(Invite).where(Invite.target_telegram_id == 42))
    assert invite is not None
    assert invite.status == "pending"


async def test_invite_by_telegram_id_falls_back_to_code_when_bot_forbidden(
    db_session, monkeypatch
):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    workspace = Workspace(name="Owner workspace")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)

    user = User(telegram_id=777777)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()

    async def fake_send_forbidden(bot, chat_id, text, **kwargs):
        raise TelegramForbiddenError(method=None, message="Forbidden")

    monkeypatch.setattr(account_module, "send_message_throttled", fake_send_forbidden)

    with TestClient(app) as client:
        _login(client, "777777")
        resp = client.post("/api/account/invites/by-telegram-id", json={"target_telegram_id": 43})

    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback"] is True
    assert "code" in body


async def test_invite_by_telegram_id_falls_back_to_code_when_chat_not_found(
    db_session, monkeypatch
):
    """Несуществующий/опечатанный telegram_id — Telegram отвечает
    TelegramBadRequest("chat not found"), не Forbidden — тоже должен уйти
    в fallback, а не 500."""
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    workspace = Workspace(name="Owner workspace")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)

    user = User(telegram_id=777777)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()

    async def fake_send_bad_request(bot, chat_id, text, **kwargs):
        raise TelegramBadRequest(method=None, message="Bad Request: chat not found")

    monkeypatch.setattr(account_module, "send_message_throttled", fake_send_bad_request)

    with TestClient(app) as client:
        _login(client, "777777")
        resp = client.post(
            "/api/account/invites/by-telegram-id", json={"target_telegram_id": 123456789}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback"] is True
    assert "code" in body
