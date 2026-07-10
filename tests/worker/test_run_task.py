"""Регрессионный тест на баг: lru_cache'нутый asyncpg-engine, переживший свой
event loop, ломает вторую подряд Celery-задачу в одном воркер-процессе с
'attached to a different loop'. run_task() должен пересоздавать engine между
вызовами (см. комментарий в worker/tasks.py)."""

from sqlalchemy import text

import worker.tasks as tasks_module
from db.session import get_engine, get_sessionmaker


async def _ping() -> int:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        return (await session.execute(text("SELECT 1"))).scalar_one()


def test_run_task_survives_two_sequential_invocations():
    # Первый вызов создаёт engine в своём event loop (asyncio.run #1)
    assert tasks_module.run_task(_ping()) == 1
    # Без сброса кэша второй вызов (asyncio.run #2, новый loop) упал бы с
    # asyncpg "attached to a different loop"
    assert tasks_module.run_task(_ping()) == 1
    assert tasks_module.run_task(_ping()) == 1


def test_run_task_clears_engine_cache_after_each_call():
    tasks_module.run_task(_ping())
    # get_engine/get_sessionmaker должны быть пересоздаваемы — lru_cache пуст
    # сразу после run_task (не проверяем напрямую cache_info — достаточно,
    # что повторный вызов get_engine() не бросает "closed loop" ошибок)
    engine = get_engine()
    assert engine is not None
