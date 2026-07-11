import hashlib

from starlette.testclient import TestClient

from api.main import app
from api.routes.posts import get_posts_by_link_ids
from db.models import Link, LinkStatus, Post


async def _make_link(db_session, **kwargs) -> Link:
    defaults = dict(
        url="https://a.com",
        normalized_url="https://a.com",
        url_hash=hashlib.sha256(b"https://a.com").hexdigest(),
        title="A",
        status=LinkStatus.done,
    )
    defaults.update(kwargs)
    link = Link(**defaults)
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)
    return link


async def test_get_posts_by_link_ids_maps_correctly(db_session):
    link = await _make_link(db_session)
    post = Post(
        chat_id=-100123,
        message_id=1,
        post_url="https://t.me/c/123/1",
        link_ids=[link.id],
    )
    db_session.add(post)
    await db_session.commit()

    result = await get_posts_by_link_ids(db_session, [link.id])
    assert result[link.id].id == post.id


async def test_get_posts_by_link_ids_empty_for_unrelated_link(db_session):
    link = await _make_link(db_session, url_hash="unrelated")

    result = await get_posts_by_link_ids(db_session, [link.id])
    assert result == {}


async def test_index_page_shows_post_link_and_usefulness_badge(db_session):
    link = await _make_link(
        db_session,
        usefulness_score=7.0,
        usefulness_breakdown={"depth": 3, "novelty": 2, "actionability": 2, "total": 7},
    )
    post = Post(
        chat_id=-100123,
        message_id=2,
        post_url="https://t.me/c/123/2",
        link_ids=[link.id],
    )
    db_session.add(post)
    await db_session.commit()

    with TestClient(app) as client:
        resp = client.get("/")

    assert resp.status_code == 200
    assert 'href="https://t.me/c/123/2"' in resp.text
    assert "7/10" in resp.text
    assert "Depth 3/4" in resp.text
