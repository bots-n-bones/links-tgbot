import os

import pytest

from db import session as db_session_module
from shared import config as config_module

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/linkcollector_test",
)


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
