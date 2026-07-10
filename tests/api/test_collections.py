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


async def test_collections_dashboard_page_renders(db_session):
    await _make_collection(db_session)
    with TestClient(app) as client:
        resp = client.get("/collections")
    assert resp.status_code == 200
    assert "Подборка недели" in resp.text
