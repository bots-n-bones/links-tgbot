from sqlalchemy import select

from db.models import ChannelParseJob, ChannelParseJobStatus, ChannelWatch, User


async def _make_jobs(db_session, workspace_id: int, count: int) -> list[ChannelParseJob]:
    jobs = []
    for i in range(count):
        job = ChannelParseJob(
            workspace_id=workspace_id,
            channel_username=f"channel{i}",
            params_json={"post_limit": 10},
            status=ChannelParseJobStatus.done,
            posts_count=i,
        )
        db_session.add(job)
        jobs.append(job)
    await db_session.commit()
    for job in jobs:
        await db_session.refresh(job)
    return jobs


async def test_history_page_renders_jobs(db_session, workspace_id, authed_client):
    await _make_jobs(db_session, workspace_id, 3)

    resp = authed_client.get("/channels")

    assert resp.status_code == 200
    assert "@channel0" in resp.text
    assert "@channel1" in resp.text
    assert "@channel2" in resp.text


async def test_history_page_orders_by_created_at_desc(db_session, workspace_id, authed_client):
    await _make_jobs(db_session, workspace_id, 3)

    resp = authed_client.get("/channels")

    # last created (channel2) should appear before the first created (channel0)
    assert resp.text.index("@channel2") < resp.text.index("@channel0")


async def test_history_page_paginates_at_20(db_session, workspace_id, authed_client):
    await _make_jobs(db_session, workspace_id, 25)

    page1 = authed_client.get("/channels")
    page2 = authed_client.get("/channels", params={"page": 2})

    assert page1.text.count("@channel") == 20
    assert page2.text.count("@channel") == 5


async def test_history_page_empty_state(db_session, authed_client):
    resp = authed_client.get("/channels")

    assert resp.status_code == 200
    assert "No channels parsed yet." in resp.text


async def test_history_page_links_to_report_when_voice_dna_requested(
    db_session, workspace_id, authed_client
):
    job = ChannelParseJob(
        workspace_id=workspace_id,
        channel_username="testchannel",
        params_json={"post_limit": 10, "voice_dna": True},
        status=ChannelParseJobStatus.done,
        posts_count=5,
    )
    db_session.add(job)
    await db_session.commit()

    resp = authed_client.get("/channels")

    assert f"/channels/parse/{job.id}/report" in resp.text


async def test_history_page_shows_who_requested_the_job(db_session, workspace_id, authed_client):
    user = await db_session.scalar(select(User).where(User.telegram_id == 900001))
    job = ChannelParseJob(
        workspace_id=workspace_id,
        requested_by_user_id=user.id,
        channel_username="testchannel",
        params_json={"post_limit": 10},
        status=ChannelParseJobStatus.done,
    )
    db_session.add(job)
    await db_session.commit()

    resp = authed_client.get("/channels")

    assert resp.status_code == 200
    assert "Test" in resp.text  # display name из логина authed_client (first_name="Test")


async def test_history_page_shows_dash_when_no_requester(db_session, workspace_id, authed_client):
    await _make_jobs(db_session, workspace_id, 1)

    resp = authed_client.get("/channels")

    assert "—" in resp.text


async def test_history_page_mine_filter_shows_only_watched_channels(
    db_session, workspace_id, authed_client
):
    user = await db_session.scalar(select(User).where(User.telegram_id == 900001))
    await _make_jobs(db_session, workspace_id, 3)  # channel0, channel1, channel2
    db_session.add(ChannelWatch(user_id=user.id, channel_username="channel1"))
    await db_session.commit()

    resp = authed_client.get("/channels", params={"mine": "true"})

    assert "@channel1" in resp.text
    assert "@channel0" not in resp.text
    assert "@channel2" not in resp.text
