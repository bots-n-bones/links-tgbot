import os

import pytest

from db import session as db_session_module
from shared import config as config_module

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/linkcollector_test",
)

WHITELISTED_USER_ID = 999


@pytest.fixture(autouse=True)
def _test_env(monkeypatch):
    """Направляет shared.config/db.session на тестовую БД и фиксированный
    whitelist, независимо от реального .env, и сбрасывает lru_cache."""
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("ALLOWED_USER_IDS", str(WHITELISTED_USER_ID))
    monkeypatch.setenv("ENV", "test")  # форсирует fake LLM/embedding в worker.rag

    config_module.get_settings.cache_clear()
    db_session_module.get_engine.cache_clear()
    db_session_module.get_sessionmaker.cache_clear()
    yield
    config_module.get_settings.cache_clear()
    db_session_module.get_engine.cache_clear()
    db_session_module.get_sessionmaker.cache_clear()
