import hashlib
import hmac
import time

from sqlalchemy import select
from starlette.testclient import TestClient

from api.main import app
from db.models import User
from shared.config import get_settings

TEST_BOT_TOKEN = "999999:test-bot-token-for-auth"


def _signed_payload(bot_token: str = TEST_BOT_TOKEN, **overrides) -> dict:
    payload = {
        "id": "555555",
        "first_name": "Ada",
        "username": "ada_lovelace",
        "auth_date": str(int(time.time())),
    }
    payload.update(overrides)
    data_check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    payload["hash"] = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return payload


async def test_login_page_renders(db_session):
    with TestClient(app) as client:
        resp = client.get("/login")
    assert resp.status_code == 200
    assert "Log in" in resp.text


async def test_login_callback_valid_payload_creates_user_and_session(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    with TestClient(app) as client:
        resp = client.get(
            "/login/callback", params=_signed_payload(), follow_redirects=False
        )

    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/"
    assert "session" in resp.cookies

    user = await db_session.scalar(select(User).where(User.telegram_id == 555555))
    assert user is not None
    assert user.username == "ada_lovelace"


async def test_login_callback_captures_avatar_from_photo_url(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    with TestClient(app) as client:
        client.get(
            "/login/callback",
            params=_signed_payload(photo_url="https://t.me/i/userpic/320/ada.jpg"),
            follow_redirects=False,
        )

    user = await db_session.scalar(select(User).where(User.telegram_id == 555555))
    assert user.avatar_url == "https://t.me/i/userpic/320/ada.jpg"


async def test_login_callback_invalid_signature_rejected(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    payload = _signed_payload(bot_token="wrong-token")
    with TestClient(app) as client:
        resp = client.get("/login/callback", params=payload)

    assert resp.status_code == 401


async def test_logout_clears_session(db_session, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()

    with TestClient(app) as client:
        client.get("/login/callback", params=_signed_payload(), follow_redirects=False)
        resp = client.post("/logout", follow_redirects=False)
        assert resp.status_code == 303

        home = client.get("/")
        assert "Log out" not in home.text
