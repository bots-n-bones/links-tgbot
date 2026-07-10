from datetime import UTC, datetime, timedelta

from sqlalchemy import select

import worker.collections as collections_module
from db.models import Link, LinkSource, LinkStatus, LinkTag, SourceType, Tag
from worker.llm import FakeLLMClient


async def _get_or_create_tag(db_session, tag_name: str) -> Tag:
    tag = await db_session.scalar(select(Tag).where(Tag.name == tag_name))
    if tag is None:
        tag = Tag(name=tag_name, slug=tag_name)
        db_session.add(tag)
        await db_session.flush()
    return tag


async def _make_tagged_link(db_session, *, url, tag_name, priority, created_days_ago, url_hash):
    now = datetime.now(UTC) - timedelta(days=created_days_ago)
    link = Link(
        url=url,
        normalized_url=url,
        url_hash=url_hash,
        title=f"T {url}",
        description="desc",
        status=LinkStatus.done,
        priority_score=priority,
        created_at=now,
    )
    db_session.add(link)
    await db_session.flush()
    tag = await _get_or_create_tag(db_session, tag_name)
    db_session.add(LinkTag(link_id=link.id, tag_id=tag.id))
    db_session.add(
        LinkSource(link_id=link.id, sender_id=1, source_type=SourceType.group, created_at=now)
    )
    await db_session.commit()
    await db_session.refresh(link)
    return link


async def test_generate_weekly_collection_groups_by_tag_within_window(db_session, monkeypatch):
    fake_llm = FakeLLMClient()
    monkeypatch.setattr(collections_module, "get_llm_client", lambda: fake_llm)

    recent = await _make_tagged_link(
        db_session,
        url="https://a.com",
        tag_name="ai",
        priority=5.0,
        created_days_ago=1,
        url_hash="h1",
    )
    await _make_tagged_link(
        db_session,
        url="https://old.com",
        tag_name="ai",
        priority=9.0,
        created_days_ago=20,
        url_hash="h2",
    )  # вне 7-дневного окна

    collection = await collections_module.generate_weekly_collection()

    assert collection is not None
    assert collection.link_ids == [recent.id]
    assert len(fake_llm.complete_calls) == 1


async def test_generate_weekly_collection_returns_none_when_nothing_recent(db_session, monkeypatch):
    fake_llm = FakeLLMClient()
    monkeypatch.setattr(collections_module, "get_llm_client", lambda: fake_llm)

    await _make_tagged_link(
        db_session,
        url="https://old.com",
        tag_name="ai",
        priority=9.0,
        created_days_ago=20,
        url_hash="h1",
    )

    collection = await collections_module.generate_weekly_collection()
    assert collection is None
    assert fake_llm.complete_calls == []


async def test_generate_weekly_collection_caps_top_n_per_tag(db_session, monkeypatch):
    fake_llm = FakeLLMClient()
    monkeypatch.setattr(collections_module, "get_llm_client", lambda: fake_llm)

    for i in range(7):
        await _make_tagged_link(
            db_session,
            url=f"https://l{i}.com",
            tag_name="ai",
            priority=float(i),
            created_days_ago=1,
            url_hash=f"h{i}",
        )

    collection = await collections_module.generate_weekly_collection()
    assert collection is not None
    assert len(collection.link_ids) == collections_module.TOP_N_PER_TAG
