"""Формула приоритета ссылки (TZ §4.4, зафиксировано в v1.1)."""

import math
from datetime import datetime

SOURCE_COUNT_WEIGHT = 1.0
UNIQUE_SENDERS_WEIGHT = 2.0
RECENCY_MAX_BONUS = 3.0
RECENCY_DECAY_DAYS = 7.0

POPULAR_MIN_UNIQUE_SENDERS = 2
POPULAR_MIN_SOURCE_COUNT = 3


def compute_priority_score(
    source_count: int,
    unique_senders: int,
    last_source_at: datetime,
    now: datetime,
) -> float:
    days_since_last = max((now - last_source_at).total_seconds() / 86400, 0.0)
    recency_bonus = RECENCY_MAX_BONUS * math.exp(-days_since_last / RECENCY_DECAY_DAYS)
    return (
        source_count * SOURCE_COUNT_WEIGHT + unique_senders * UNIQUE_SENDERS_WEIGHT + recency_bonus
    )


def is_popular(source_count: int, unique_senders: int) -> bool:
    return unique_senders >= POPULAR_MIN_UNIQUE_SENDERS or source_count >= POPULAR_MIN_SOURCE_COUNT
