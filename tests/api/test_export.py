import hashlib

from starlette.testclient import TestClient

from api.main import app
from db.models import Link, LinkStatus, Post


async def _make_link(db_session) -> Link:
    link = Link(
        url="https://a.com",
        normalized_url="https://a.com",
        url_hash=hashlib.sha256(b"https://a.com").hexdigest(),
        title="A great article",
        description="Why it matters",
        area="tech",
        usefulness_score=7.0,
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)
    return link


async def _make_post(db_session) -> Post:
    post = Post(
        chat_id=-100123,
        message_id=1,
        chat_title="Team chat",
        text="check this out",
        post_url="https://t.me/c/123/1",
        summary="A note.",
        area="tech",
    )
    db_session.add(post)
    await db_session.commit()
    await db_session.refresh(post)
    return post


async def test_export_links_csv(db_session):
    await _make_link(db_session)
    with TestClient(app) as client:
        resp = client.get("/export/links.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="links.csv"' in resp.headers["content-disposition"]
    assert "A great article" in resp.text
    assert "https://a.com" in resp.text
    assert "7.0" in resp.text


async def test_export_links_md(db_session):
    await _make_link(db_session)
    with TestClient(app) as client:
        resp = client.get("/export/links.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "| id | title | url |" in resp.text
    assert "A great article" in resp.text


async def test_export_links_excludes_hidden(db_session):
    link = await _make_link(db_session)
    link.is_hidden = True
    await db_session.commit()

    with TestClient(app) as client:
        resp = client.get("/export/links.csv")
    assert "A great article" not in resp.text


async def test_export_posts_csv(db_session):
    await _make_post(db_session)
    with TestClient(app) as client:
        resp = client.get("/export/posts.csv")
    assert resp.status_code == 200
    assert 'filename="posts.csv"' in resp.headers["content-disposition"]
    assert "check this out" in resp.text
    assert "https://t.me/c/123/1" in resp.text


async def test_export_posts_md(db_session):
    await _make_post(db_session)
    with TestClient(app) as client:
        resp = client.get("/export/posts.md")
    assert resp.status_code == 200
    assert "| id | post_url |" in resp.text
    assert "check this out" in resp.text


async def test_export_posts_excludes_hidden(db_session):
    post = await _make_post(db_session)
    post.is_hidden = True
    await db_session.commit()

    with TestClient(app) as client:
        resp = client.get("/export/posts.csv")
    assert "check this out" not in resp.text
