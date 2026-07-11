from datetime import date

from starlette.testclient import TestClient

from api.main import app
from db.models import Collection


async def _make_collection(db_session, title: str = "Подборка недели") -> Collection:
    c = Collection(
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


async def test_list_collections(db_session):
    await _make_collection(db_session)
    with TestClient(app) as client:
        resp = client.get("/api/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Подборка недели"


async def test_get_collection_detail(db_session):
    c = await _make_collection(db_session)
    with TestClient(app) as client:
        resp = client.get(f"/api/collections/{c.id}")
    assert resp.status_code == 200
    assert resp.json()["summary_md"] == "# Итоги\nТекст подборки"


async def test_get_collection_404(db_session):
    with TestClient(app) as client:
        resp = client.get("/api/collections/999999")
    assert resp.status_code == 404


async def _make_weekly_digest(db_session) -> Collection:
    from worker.collections import WEEKLY_DIGEST_THEME

    c = Collection(
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


async def test_weekly_digest_dashboard_page_lists_digest(db_session):
    await _make_weekly_digest(db_session)
    with TestClient(app) as client:
        resp = client.get("/weekly-digest")
    assert resp.status_code == 200
    assert "1 article" in resp.text


async def test_weekly_digest_detail_page_shows_articles(db_session):
    c = await _make_weekly_digest(db_session)
    with TestClient(app) as client:
        resp = client.get(f"/weekly-digest/{c.id}")
    assert resp.status_code == 200
    assert '<a href="https://a.com"' in resp.text
    assert "Great find" in resp.text
    assert "why it matters" in resp.text


async def test_weekly_digest_detail_page_404_for_wrong_theme(db_session):
    await _make_collection(db_session)  # theme="ai", не weekly-digest
    with TestClient(app) as client:
        resp = client.get("/weekly-digest/1")
    assert resp.status_code == 404
