"""Троттлинг исходящих сообщений Telegram (NF-05): ~30/сек глобально,
~1/сек на чат. Используется и ботом, и воркером при ответах после обработки."""

import asyncio
import time
from collections import defaultdict


class TelegramThrottle:
    def __init__(
        self, global_rate_per_sec: float = 25.0, per_chat_rate_per_sec: float = 1.0
    ) -> None:
        self._global_interval = 1.0 / global_rate_per_sec
        self._chat_interval = 1.0 / per_chat_rate_per_sec
        self._lock = asyncio.Lock()
        self._last_global = 0.0
        self._last_by_chat: dict[int, float] = defaultdict(float)

    async def acquire(self, chat_id: int) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_global = self._last_global + self._global_interval - now
            wait_chat = self._last_by_chat[chat_id] + self._chat_interval - now
            wait_time = max(wait_global, wait_chat, 0.0)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            now = time.monotonic()
            self._last_global = now
            self._last_by_chat[chat_id] = now


_throttle = TelegramThrottle()


async def send_message_throttled(bot, chat_id: int, text: str, **kwargs) -> None:
    await _throttle.acquire(chat_id)
    await bot.send_message(chat_id, text, **kwargs)
