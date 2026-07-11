from starlette.testclient import TestClient

from api.main import app
from db.models import Post


async def _make_post(db_session, **kwargs) -> Post:
    defaults = dict(
        chat_id=-100123,
        message_id=1,
        chat_title="Team chat",
        text="hello",
        post_url="https://t.me/c/123/1",
        summary="A quick note about something useful.",
        area="tech",
    )
    defaults.update(kwargs)
    post = Post(**defaults)
    db_session.add(post)
    await db_session.commit()
    await db_session.refresh(post)
    return post


async def test_posts_page_renders_list(db_session):
    await _make_post(db_session)

    with TestClient(app) as client:
        resp = client.get("/posts")
    assert resp.status_code == 200
    assert "A quick note about something useful." in resp.text
    assert 'href="https://t.me/c/123/1"' in resp.text


async def test_posts_page_filters_by_area(db_session):
    await _make_post(db_session, message_id=2, area="design")
    await _make_post(db_session, message_id=3, area="tech")

    with TestClient(app) as client:
        resp = client.get("/posts", params={"area": "design"})
    assert resp.status_code == 200
    data = resp.text
    # только один пост из двух должен попасть в выдачу
    assert data.count("Team chat —") == 1


async def test_posts_page_empty_state(db_session):
    with TestClient(app) as client:
        resp = client.get("/posts")
    assert resp.status_code == 200
    assert "No posts yet." in resp.text
