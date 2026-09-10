"""Локальный вход без Telegram — и его выключенность вне разработки."""

import pytest
from fastapi.testclient import TestClient

import shared.config as config_module
from api.main import app
from db.models import User, Workspace, WorkspaceMember


@pytest.fixture
def client():
    """Незалогиненный клиент — в отличие от authed_client, который заходит
    через Telegram Login Widget. Здесь проверяется как раз вход."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def _as_env(monkeypatch):
    def _set(value: str):
        monkeypatch.setenv("ENV", value)
        config_module.get_settings.cache_clear()

    yield _set
    config_module.get_settings.cache_clear()


async def _seed_user(db_session) -> User:
    workspace = Workspace(name="Команда")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)

    user = User(telegram_id=4242, full_name="Аня")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id))
    await db_session.commit()
    return user


async def test_dev_login_signs_in_the_seeded_user(db_session, client, _as_env):
    _as_env("dev")
    user = await _seed_user(db_session)

    resp = client.get("/dev-login", follow_redirects=False)
    assert resp.status_code in (302, 307)

    # Дальше дашборд открывается уже как залогиненный.
    assert client.get("/").status_code == 200
    assert user.full_name in client.get("/").text


async def test_dev_login_is_absent_outside_development(db_session, client, _as_env):
    """404, а не 403: обход авторизации не должен сообщать о своём
    существовании там, где он выключен."""
    _as_env("prod")
    await _seed_user(db_session)

    assert client.get("/dev-login", follow_redirects=False).status_code == 404


async def test_dev_login_says_what_to_do_when_there_is_nobody(db_session, client, _as_env):
    _as_env("dev")

    resp = client.get("/dev-login", follow_redirects=False)
    assert resp.status_code == 503
    assert "make seed" in resp.text
