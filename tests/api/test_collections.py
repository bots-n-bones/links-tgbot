from datetime import date

from starlette.testclient import TestClient

from api.main import app
from db.models import Collection


async def _make_collection(
    db_session, workspace_id: int, title: str = "Подборка недели"
) -> Collection:
    c = Collection(
        workspace_id=workspace_id,
        title=title,
        theme="ai",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 7),
        summary_md="# Итоги\nТекст подборки",
        link_ids=[1, 2],
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


async def test_list_collections(db_session, workspace_id, authed_client):
    await _make_collection(db_session, workspace_id)
    resp = authed_client.get("/api/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Подборка недели"


async def test_get_collection_detail(db_session, workspace_id, authed_client):
    c = await _make_collection(db_session, workspace_id)
    resp = authed_client.get(f"/api/collections/{c.id}")
    assert resp.status_code == 200
    assert resp.json()["summary_md"] == "# Итоги\nТекст подборки"


async def test_get_collection_404(db_session, authed_client):
    resp = authed_client.get("/api/collections/999999")
    assert resp.status_code == 404


async def _make_weekly_digest(db_session, workspace_id: int) -> Collection:
    from worker.collections import WEEKLY_DIGEST_THEME

    c = Collection(
        workspace_id=workspace_id,
        title="Weekly digest — Jul 07, 2026",
        theme=WEEKLY_DIGEST_THEME,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 7),
        summary_md="",
        articles=[{"title": "Great find", "url": "https://a.com", "description": "why it matters"}],
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


async def _make_daily_digest(db_session, workspace_id: int) -> Collection:
    from datetime import UTC, datetime

    from worker.collections import DAILY_DIGEST_THEME

    c = Collection(
        workspace_id=workspace_id,
        title="Daily digest — Jul 07, 2026",
        theme=DAILY_DIGEST_THEME,
        summary_md="",
        articles=[
            {"title": "Fresh find", "url": "https://b.com", "description": "hot off the press"}
        ],
        created_at=datetime.now(UTC),
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


async def test_digest_page_lists_weekly_digest(db_session, workspace_id, authed_client):
    await _make_weekly_digest(db_session, workspace_id)
    resp = authed_client.get("/digest")
    assert resp.status_code == 200
    assert "1 article" in resp.text
    assert "Weekly" in resp.text


async def test_digest_page_lists_both_daily_and_weekly_together(
    db_session, workspace_id, authed_client
):
    await _make_daily_digest(db_session, workspace_id)
    await _make_weekly_digest(db_session, workspace_id)
    resp = authed_client.get("/digest")
    assert resp.status_code == 200
    assert "Fresh find" not in resp.text  # список показывает только даты/теги, не статьи
    assert "Daily" in resp.text
    assert "Weekly" in resp.text


async def test_digest_detail_page_shows_articles(db_session, workspace_id, authed_client):
    c = await _make_weekly_digest(db_session, workspace_id)
    resp = authed_client.get(f"/digest/{c.id}")
    assert resp.status_code == 200
    assert '<a href="https://a.com"' in resp.text
    assert "Great find" in resp.text
    assert "why it matters" in resp.text


async def test_digest_detail_page_404_for_wrong_theme(db_session, workspace_id, authed_client):
    c = await _make_collection(db_session, workspace_id)  # theme="ai", не daily/weekly-digest
    resp = authed_client.get(f"/digest/{c.id}")
    assert resp.status_code == 404


async def test_old_weekly_digest_url_redirects_to_digest(db_session, workspace_id):
    c = await _make_weekly_digest(db_session, workspace_id)
    with TestClient(app) as client:
        resp = client.get("/weekly-digest", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/digest"

        resp = client.get(f"/weekly-digest/{c.id}", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == f"/digest/{c.id}"


async def test_old_daily_digest_url_redirects_to_digest(db_session):
    with TestClient(app) as client:
        resp = client.get("/daily-digest", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/digest"

        resp = client.get("/daily-digest/5", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/digest/5"
