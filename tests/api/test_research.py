import hashlib

from starlette.testclient import TestClient

import api.routes.research as research_module
from api.main import app
from db.models import Link, LinkStatus, ResearchReport


async def _make_link(db_session, url: str = "https://a.com") -> Link:
    link = Link(
        url=url,
        normalized_url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title="A",
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)
    return link


class FakeTask:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def delay(self, *args) -> None:
        self.calls.append(args)


async def test_trigger_research_enqueues_when_no_existing_report(db_session, monkeypatch):
    link = await _make_link(db_session)
    fake_task = FakeTask()
    monkeypatch.setattr(research_module, "generate_research_report", fake_task)

    with TestClient(app) as client:
        resp = client.post(f"/api/links/{link.id}/research")
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"
    assert fake_task.calls == [(link.id,)]


async def test_trigger_research_returns_cached_when_report_exists(db_session):
    link = await _make_link(db_session)
    report = ResearchReport(link_id=link.id, topic="t", report_md="md", model="gpt-4o")
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    with TestClient(app) as client:
        resp = client.post(f"/api/links/{link.id}/research")
    assert resp.json() == {"status": "done", "research_id": report.id}


async def test_trigger_research_404_for_missing_link(db_session):
    with TestClient(app) as client:
        resp = client.post("/api/links/999999/research")
    assert resp.status_code == 404


async def test_get_research_returns_report(db_session):
    link = await _make_link(db_session)
    report = ResearchReport(
        link_id=link.id,
        topic="t",
        report_md="md текст",
        sources_json=[{"url": "https://x.com"}],
        model="gpt-4o",
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    with TestClient(app) as client:
        resp = client.get(f"/api/research/{report.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["report_md"] == "md текст"
    assert data["sources"] == [{"url": "https://x.com"}]


async def test_get_research_404(db_session):
    with TestClient(app) as client:
        resp = client.get("/api/research/999999")
    assert resp.status_code == 404


async def test_add_links_from_research_enqueues(db_session, monkeypatch):
    link = await _make_link(db_session)
    report = ResearchReport(
        link_id=link.id, topic="t", report_md="md", sources_json=[], model="gpt-4o"
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    fake_task = FakeTask()
    monkeypatch.setattr(research_module, "add_research_links", fake_task)

    with TestClient(app) as client:
        resp = client.post(f"/api/research/{report.id}/add-links")
    assert resp.status_code == 202
    assert resp.json() == {"status": "queued"}
    assert fake_task.calls == [(report.id,)]
