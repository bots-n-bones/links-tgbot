from starlette.testclient import TestClient

import api.main as main_module
from api.main import app
from db.models import ChannelParseJob


async def test_channel_parse_form_renders(db_session):
    with TestClient(app) as client:
        resp = client.get("/channels/parse")
    assert resp.status_code == 200
    assert "Parse a channel" in resp.text


async def test_channel_parse_submit_creates_job_and_enqueues(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(
        main_module.run_channel_parse_job, "delay", lambda job_id: enqueued.append(job_id)
    )

    with TestClient(app) as client:
        resp = client.post(
            "/channels/parse",
            data={"channel_input": "@testchannel", "post_limit": "50"},
            follow_redirects=False,
        )

    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/channels/parse/")
    assert len(enqueued) == 1

    job = await db_session.get(ChannelParseJob, enqueued[0])
    assert job.channel_username == "testchannel"
    assert job.params_json["post_limit"] == 50


async def test_channel_parse_submit_rejects_invalid_username(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(
        main_module.run_channel_parse_job, "delay", lambda job_id: enqueued.append(job_id)
    )

    with TestClient(app) as client:
        resp = client.post("/channels/parse", data={"channel_input": "not a valid channel!"})

    assert resp.status_code == 200
    assert "Enter a valid public channel" in resp.text
    assert enqueued == []


async def test_channel_parse_submit_clamps_post_limit_to_max(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(
        main_module.run_channel_parse_job, "delay", lambda job_id: enqueued.append(job_id)
    )

    with TestClient(app) as client:
        client.post(
            "/channels/parse",
            data={"channel_input": "@testchannel", "post_limit": "99999"},
            follow_redirects=False,
        )

    job = await db_session.get(ChannelParseJob, enqueued[0])
    assert job.params_json["post_limit"] == 200  # channel_parse_max_posts default


async def test_channel_parse_progress_page_renders(db_session):
    job = ChannelParseJob(channel_username="testchannel", params_json={"post_limit": 10})
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}")
    assert resp.status_code == 200
    assert "testchannel" in resp.text
    assert 'data-job-id="' + str(job.id) in resp.text


async def test_channel_parse_progress_page_404_for_missing_job(db_session):
    with TestClient(app) as client:
        resp = client.get("/channels/parse/999999")
    assert resp.status_code == 404
