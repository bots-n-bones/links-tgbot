from starlette.testclient import TestClient

import api.main as main_module
from api.main import app
from db.models import RawMessage, SourceType


async def test_add_link_manual_enqueues_processing(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(main_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    with TestClient(app) as client:
        resp = client.post("/links/add", data={"url": "https://example.com/manual"})

    assert resp.status_code == 200
    assert "Added" in resp.text
    assert len(enqueued) == 1

    row = (await db_session.execute(RawMessage.__table__.select())).mappings().one()
    assert row["source_type"] == SourceType.manual
    assert row["text"] == "https://example.com/manual"


async def test_add_link_manual_rejects_empty_url(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(main_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    with TestClient(app) as client:
        resp = client.post("/links/add", data={"url": "   "})

    assert resp.status_code == 200
    assert "Enter a URL" in resp.text
    assert enqueued == []
