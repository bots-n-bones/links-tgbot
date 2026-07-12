from datetime import UTC, datetime

from starlette.testclient import TestClient

from api.main import app
from db.models import ChannelParsedPost, ChannelParseJob


async def _make_job_with_posts(db_session) -> ChannelParseJob:
    job = ChannelParseJob(
        channel_username="testchannel",
        params_json={"post_limit": 10},
        posts_count=2,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    db_session.add_all(
        [
            ChannelParsedPost(
                job_id=job.id,
                message_id=1,
                post_url="https://t.me/testchannel/1",
                text="older, fewer views",
                published_at=datetime(2026, 7, 1, tzinfo=UTC),
                views=10,
                reactions_total=1,
                comments_count=0,
            ),
            ChannelParsedPost(
                job_id=job.id,
                message_id=2,
                post_url="https://t.me/testchannel/2",
                text="newer, more views",
                published_at=datetime(2026, 7, 5, tzinfo=UTC),
                views=500,
                reactions_total=20,
                comments_count=3,
            ),
        ]
    )
    await db_session.commit()
    return job


async def test_results_page_renders_posts(db_session):
    job = await _make_job_with_posts(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/results")

    assert resp.status_code == 200
    assert "newer, more views" in resp.text
    assert "older, fewer views" in resp.text


async def test_results_page_default_sort_is_newest_first(db_session):
    job = await _make_job_with_posts(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/results")

    assert resp.text.index("newer, more views") < resp.text.index("older, fewer views")


async def test_results_page_sort_by_views_ascending_is_not_default(db_session):
    job = await _make_job_with_posts(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/results", params={"sort": "views"})

    # by views desc: the 500-view post should still come first
    assert resp.text.index("newer, more views") < resp.text.index("older, fewer views")


async def test_results_page_404_for_missing_job(db_session):
    with TestClient(app) as client:
        resp = client.get("/channels/parse/999999/results")
    assert resp.status_code == 404
