from datetime import UTC, datetime, timedelta

import worker.collections as collections_module
from db.models import Link, LinkSource, LinkStatus, SourceType


async def _make_link_with_source(
    db_session, *, url, priority, created_days_ago, url_hash, is_hidden=False
):
    now = datetime.now(UTC) - timedelta(days=created_days_ago)
    link = Link(
        url=url,
        normalized_url=url,
        url_hash=url_hash,
        title=f"T {url}",
        status=LinkStatus.done,
        priority_score=priority,
        is_hidden=is_hidden,
        created_at=now,
    )
    db_session.add(link)
    await db_session.flush()
    db_session.add(
        LinkSource(link_id=link.id, sender_id=1, source_type=SourceType.group, created_at=now)
    )
    await db_session.commit()
    await db_session.refresh(link)
    return link


async def test_generate_daily_top3_picks_highest_priority(db_session):
    low = await _make_link_with_source(
        db_session, url="https://a.com", priority=1.0, created_days_ago=1, url_hash="h1"
    )
    mid = await _make_link_with_source(
        db_session, url="https://b.com", priority=5.0, created_days_ago=1, url_hash="h2"
    )
    high = await _make_link_with_source(
        db_session, url="https://c.com", priority=9.0, created_days_ago=1, url_hash="h3"
    )

    collection = await collections_module.generate_daily_top3()

    assert collection is not None
    assert collection.theme == collections_module.DAILY_TOP3_THEME
    assert collection.link_ids == [high.id, mid.id, low.id]


async def test_generate_daily_top3_caps_at_three(db_session):
    for i in range(5):
        await _make_link_with_source(
            db_session,
            url=f"https://l{i}.com",
            priority=float(i),
            created_days_ago=1,
            url_hash=f"h{i}",
        )

    collection = await collections_module.generate_daily_top3()
    assert collection is not None
    assert len(collection.link_ids) == 3


async def test_generate_daily_top3_excludes_hidden_and_stale(db_session):
    await _make_link_with_source(
        db_session,
        url="https://hidden.com",
        priority=9.0,
        created_days_ago=1,
        url_hash="h-hidden",
        is_hidden=True,
    )
    await _make_link_with_source(
        db_session, url="https://stale.com", priority=9.0, created_days_ago=30, url_hash="h-stale"
    )

    collection = await collections_module.generate_daily_top3()
    assert collection is None


async def test_generate_daily_top3_returns_none_when_nothing_recent(db_session):
    collection = await collections_module.generate_daily_top3()
    assert collection is None
