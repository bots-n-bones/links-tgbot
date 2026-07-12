from starlette.testclient import TestClient

from api.main import app
from db.models import ChannelParseJob, ChannelParseJobStatus


async def _make_job(db_session, **kwargs) -> ChannelParseJob:
    defaults = dict(channel_username="testchannel", params_json={"post_limit": 50})
    defaults.update(kwargs)
    job = ChannelParseJob(**defaults)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


async def test_status_endpoint_reports_progress(db_session):
    job = await _make_job(
        db_session,
        status=ChannelParseJobStatus.scraping,
        progress_current=15,
        progress_total=50,
    )

    with TestClient(app) as client:
        resp = client.get(f"/api/channels/parse/{job.id}/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "scraping"
    assert data["progress_current"] == 15
    assert data["progress_total"] == 50
    assert data["progress_pct"] == 30.0


async def test_status_endpoint_handles_zero_total(db_session):
    job = await _make_job(db_session, progress_total=0, progress_current=0)

    with TestClient(app) as client:
        resp = client.get(f"/api/channels/parse/{job.id}/status")

    assert resp.status_code == 200
    assert resp.json()["progress_pct"] == 0.0


async def test_status_endpoint_reports_failure(db_session):
    job = await _make_job(
        db_session, status=ChannelParseJobStatus.failed, error_message="Channel not found"
    )

    with TestClient(app) as client:
        resp = client.get(f"/api/channels/parse/{job.id}/status")

    data = resp.json()
    assert data["status"] == "failed"
    assert data["error_message"] == "Channel not found"


async def test_status_endpoint_404_for_missing_job(db_session):
    with TestClient(app) as client:
        resp = client.get("/api/channels/parse/999999/status")
    assert resp.status_code == 404
