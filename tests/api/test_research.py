import hashlib

import api.routes.research as research_module
from db.models import Link, LinkStatus, ResearchReport


async def _make_link(db_session, workspace_id: int, url: str = "https://a.com") -> Link:
    link = Link(
        workspace_id=workspace_id,
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


async def test_trigger_research_enqueues_when_no_existing_report(
    db_session, workspace_id, authed_client, monkeypatch
):
    link = await _make_link(db_session, workspace_id)
    fake_task = FakeTask()
    monkeypatch.setattr(research_module, "generate_research_report", fake_task)

    resp = authed_client.post(f"/api/links/{link.id}/research")
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"
    assert fake_task.calls == [(link.id,)]


async def test_trigger_research_returns_cached_when_report_exists(
    db_session, workspace_id, authed_client
):
    link = await _make_link(db_session, workspace_id)
    report = ResearchReport(
        workspace_id=workspace_id, link_id=link.id, topic="t", report_md="md", model="gpt-4o"
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    resp = authed_client.post(f"/api/links/{link.id}/research")
    assert resp.json() == {"status": "done", "research_id": report.id}


async def test_trigger_research_404_for_missing_link(db_session, authed_client):
    resp = authed_client.post("/api/links/999999/research")
    assert resp.status_code == 404


async def test_get_research_returns_report(db_session, workspace_id, authed_client):
    link = await _make_link(db_session, workspace_id)
    report = ResearchReport(
        workspace_id=workspace_id,
        link_id=link.id,
        topic="t",
        report_md="md текст",
        sources_json=[{"url": "https://x.com"}],
        model="gpt-4o",
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    resp = authed_client.get(f"/api/research/{report.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["report_md"] == "md текст"
    assert data["sources"] == [{"url": "https://x.com"}]


async def test_get_research_404(db_session, authed_client):
    resp = authed_client.get("/api/research/999999")
    assert resp.status_code == 404


async def test_add_links_from_research_enqueues(
    db_session, workspace_id, authed_client, monkeypatch
):
    link = await _make_link(db_session, workspace_id)
    report = ResearchReport(
        workspace_id=workspace_id,
        link_id=link.id,
        topic="t",
        report_md="md",
        sources_json=[],
        model="gpt-4o",
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    fake_task = FakeTask()
    monkeypatch.setattr(research_module, "add_research_links", fake_task)

    resp = authed_client.post(f"/api/research/{report.id}/add-links")
    assert resp.status_code == 202
    assert resp.json() == {"status": "queued"}
    assert fake_task.calls == [(report.id,)]
