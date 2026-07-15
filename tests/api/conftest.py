import hashlib
import hmac
import os
import time

import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from api.main import app
from db import session as db_session_module
from db.models import User, WorkspaceMember, WorkspaceRole
from shared import config as config_module

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/linkcollector_test",
)

TEST_BOT_TOKEN = "999999:test-bot-token-for-api-tests"


@pytest.fixture(autouse=True)
def _test_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("ENV", "test")

    config_module.get_settings.cache_clear()
    db_session_module.get_engine.cache_clear()
    db_session_module.get_sessionmaker.cache_clear()
    yield
    config_module.get_settings.cache_clear()
    db_session_module.get_engine.cache_clear()
    db_session_module.get_sessionmaker.cache_clear()


def _signed_login_payload(telegram_id: int, bot_token: str = TEST_BOT_TOKEN) -> dict:
    payload = {"id": str(telegram_id), "first_name": "Test", "auth_date": str(int(time.time()))}
    data_check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return payload


@pytest_asyncio.fixture
async def authed_client(db_session, workspace_id, monkeypatch):
    """TestClient, залогиненный через Telegram Login Widget и привязанный к
    workspace_id (фикстура из tests/conftest.py) с ролью owner — большинству
    api-тестов дашборда после волны 4 нужен именно такой клиент, т.к. каждый
    роут требует Depends(get_current_workspace_id)."""
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    config_module.get_settings.cache_clear()

    telegram_id = 900001
    user = User(telegram_id=telegram_id)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()

    with TestClient(app) as client:
        resp = client.get(
            "/login/callback", params=_signed_login_payload(telegram_id), follow_redirects=False
        )
        assert resp.status_code in (302, 307)
        yield client
