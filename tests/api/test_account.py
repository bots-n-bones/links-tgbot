import hashlib
import hmac
import time

from starlette.testclient import TestClient

from api.main import app
from db.models import User, Workspace, WorkspaceMember, WorkspaceRole
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


async def test_nickname_updates_for_logged_in_user(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    with TestClient(app) as client:
        _login(client, "777777")

        resp = client.patch("/api/account/nickname", json={"display_name": "Ada"})
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Ada"

        account_page = client.get("/account")
        assert "Ada" in account_page.text


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
