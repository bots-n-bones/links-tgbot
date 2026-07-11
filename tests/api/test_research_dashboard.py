import hashlib

from starlette.testclient import TestClient

from api.main import app
from db.models import Link, LinkStatus, ResearchReport


async def _make_link_with_report(db_session, *, report_md: str) -> tuple[Link, ResearchReport]:
    link = Link(
        url="https://a.com",
        normalized_url="a.com",
        url_hash=hashlib.sha256(b"a").hexdigest(),
        title="A",
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.flush()
    report = ResearchReport(link_id=link.id, report_md=report_md, sources_json=[{"url": "x"}])
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(link)
    await db_session.refresh(report)
    return link, report


async def test_research_status_renders_markdown_links_as_html(db_session):
    link, report = await _make_link_with_report(
        db_session, report_md="See [Great article](https://example.com/a) for more."
    )

    with TestClient(app) as client:
        resp = client.get(f"/links/{link.id}/research/status")
    assert resp.status_code == 200
    assert '<a href="https://example.com/a">Great article</a>' in resp.text
    assert "[Great article]" not in resp.text


async def test_research_status_shows_source_count(db_session):
    link, report = await _make_link_with_report(db_session, report_md="Report body.")

    with TestClient(app) as client:
        resp = client.get(f"/links/{link.id}/research/status")
    assert "Sources found: 1" in resp.text


async def test_download_research_report_returns_markdown_file(db_session):
    link, report = await _make_link_with_report(db_session, report_md="# Report\nBody text.")

    with TestClient(app) as client:
        resp = client.get(f"/research/{report.id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert f"research-{report.id}.md" in resp.headers["content-disposition"]
    assert resp.text == "# Report\nBody text."


async def test_download_research_report_404_for_missing(db_session):
    with TestClient(app) as client:
        resp = client.get("/research/999999/download")
    assert resp.status_code == 404
