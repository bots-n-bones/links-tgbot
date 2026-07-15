import api.main as main_module
from db.models import ChannelParseJob


async def test_channel_parse_form_renders(db_session, authed_client):
    resp = authed_client.get("/channels/parse")
    assert resp.status_code == 200
    assert "Parse a channel" in resp.text


async def test_channel_parse_submit_creates_job_and_enqueues(
    db_session, authed_client, monkeypatch
):
    enqueued: list[int] = []
    monkeypatch.setattr(
        main_module.run_channel_parse_job, "delay", lambda job_id: enqueued.append(job_id)
    )

    authed_client.follow_redirects = False
    resp = authed_client.post(
        "/channels/parse",
        data={"channel_input": "@testchannel", "post_limit": "50"},
    )

    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/channels/parse/")
    assert len(enqueued) == 1

    job = await db_session.get(ChannelParseJob, enqueued[0])
    assert job.channel_username == "testchannel"
    assert job.params_json["post_limit"] == 50


async def test_channel_parse_submit_rejects_invalid_username(
    db_session, authed_client, monkeypatch
):
    enqueued: list[int] = []
    monkeypatch.setattr(
        main_module.run_channel_parse_job, "delay", lambda job_id: enqueued.append(job_id)
    )

    resp = authed_client.post("/channels/parse", data={"channel_input": "not a valid channel!"})

    assert resp.status_code == 200
    assert "Enter a valid public channel" in resp.text
    assert enqueued == []


async def test_channel_parse_submit_clamps_post_limit_to_max(
    db_session, authed_client, monkeypatch
):
    enqueued: list[int] = []
    monkeypatch.setattr(
        main_module.run_channel_parse_job, "delay", lambda job_id: enqueued.append(job_id)
    )

    authed_client.follow_redirects = False
    authed_client.post(
        "/channels/parse",
        data={"channel_input": "@testchannel", "post_limit": "99999"},
    )

    job = await db_session.get(ChannelParseJob, enqueued[0])
    assert job.params_json["post_limit"] == 200  # channel_parse_max_posts default


async def test_channel_parse_progress_page_renders(db_session, workspace_id, authed_client):
    job = ChannelParseJob(
        workspace_id=workspace_id, channel_username="testchannel", params_json={"post_limit": 10}
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    resp = authed_client.get(f"/channels/parse/{job.id}")
    assert resp.status_code == 200
    assert "testchannel" in resp.text
    assert 'data-job-id="' + str(job.id) in resp.text


async def test_channel_parse_progress_page_404_for_missing_job(db_session, authed_client):
    resp = authed_client.get("/channels/parse/999999")
    assert resp.status_code == 404
