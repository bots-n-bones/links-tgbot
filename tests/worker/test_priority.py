from datetime import UTC, datetime, timedelta

import pytest

from worker.priority import compute_priority_score, is_popular

NOW = datetime(2026, 7, 10, tzinfo=UTC)


def test_recency_bonus_at_zero_days():
    score = compute_priority_score(source_count=0, unique_senders=0, last_source_at=NOW, now=NOW)
    assert score == pytest.approx(3.0, abs=0.01)


def test_recency_bonus_at_seven_days():
    last = NOW - timedelta(days=7)
    score = compute_priority_score(source_count=0, unique_senders=0, last_source_at=last, now=NOW)
    assert score == pytest.approx(1.1, abs=0.05)


def test_recency_bonus_at_fourteen_days():
    last = NOW - timedelta(days=14)
    score = compute_priority_score(source_count=0, unique_senders=0, last_source_at=last, now=NOW)
    assert score == pytest.approx(0.4, abs=0.05)


def test_full_formula_combines_all_terms():
    score = compute_priority_score(source_count=3, unique_senders=2, last_source_at=NOW, now=NOW)
    # 3*1.0 + 2*2.0 + ~3.0 recency
    assert score == pytest.approx(10.0, abs=0.01)


def test_score_never_negative_for_future_timestamp():
    future = NOW + timedelta(days=1)
    score = compute_priority_score(source_count=0, unique_senders=0, last_source_at=future, now=NOW)
    assert score >= 0


def test_is_popular_by_unique_senders():
    assert is_popular(source_count=1, unique_senders=2) is True


def test_is_popular_by_source_count():
    assert is_popular(source_count=3, unique_senders=1) is True


def test_not_popular():
    assert is_popular(source_count=1, unique_senders=1) is False
