"""NF-04: алерт админу при 10+ ошибок подряд. Использует реальный Redis
(localhost:6379/1 — отдельная БД, чтобы не пересекаться с dev-воркером на db 0)."""

import pytest

import worker.tasks as tasks_module
from shared import config as config_module


@pytest.fixture(autouse=True)
def _use_test_redis_db(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


async def test_alert_fires_once_at_threshold_and_not_again(monkeypatch):
    alerts_sent: list[int] = []

    async def fake_send_alert(count: int) -> None:
        alerts_sent.append(count)

    monkeypatch.setattr(tasks_module, "_send_admin_alert", fake_send_alert)

    await tasks_module._record_outcome(True)  # сброс перед тестом

    for _ in range(tasks_module.ALERT_FAILURE_THRESHOLD - 1):
        await tasks_module._record_outcome(False)
    assert alerts_sent == []

    await tasks_module._record_outcome(False)  # достигли порога
    assert alerts_sent == [tasks_module.ALERT_FAILURE_THRESHOLD]

    await tasks_module._record_outcome(False)  # не шлём повторно на каждой следующей ошибке
    assert alerts_sent == [tasks_module.ALERT_FAILURE_THRESHOLD]


async def test_success_resets_counter_and_rearms_alert(monkeypatch):
    alerts_sent: list[int] = []
    monkeypatch.setattr(
        tasks_module, "_send_admin_alert", lambda count: alerts_sent.append(count) or None
    )

    await tasks_module._record_outcome(True)
    for _ in range(tasks_module.ALERT_FAILURE_THRESHOLD):
        await tasks_module._record_outcome(False)
    assert len(alerts_sent) == 1

    await tasks_module._record_outcome(True)  # успех — сброс

    for _ in range(tasks_module.ALERT_FAILURE_THRESHOLD):
        await tasks_module._record_outcome(False)
    assert len(alerts_sent) == 2  # алерт снова сработал после сброса


async def test_send_admin_alert_noop_without_bot_token(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("ADMIN_USER_ID", "587290940")
    config_module.get_settings.cache_clear()

    called = []
    monkeypatch.setattr(tasks_module, "send_message_throttled", lambda *a, **kw: called.append(1))

    await tasks_module._send_admin_alert(10)
    assert called == []


async def test_send_admin_alert_noop_without_admin_id(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("ADMIN_USER_ID", "")
    config_module.get_settings.cache_clear()

    called = []
    monkeypatch.setattr(tasks_module, "send_message_throttled", lambda *a, **kw: called.append(1))

    await tasks_module._send_admin_alert(10)
    assert called == []
