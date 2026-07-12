from datetime import UTC, datetime

from starlette.testclient import TestClient

from api.main import app
from db.models import ChannelParsedPost, ChannelParseJob


async def _make_job_with_post(db_session) -> ChannelParseJob:
    job = ChannelParseJob(channel_username="testchannel", params_json={"post_limit": 10})
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    db_session.add(
        ChannelParsedPost(
            job_id=job.id,
            message_id=1,
            post_url="https://t.me/testchannel/1",
            text="hello world",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            views=42,
            reactions_total=3,
            comments_count=1,
            word_count=2,
            is_forward=False,
            has_media=False,
        )
    )
    await db_session.commit()
    return job


async def test_export_csv_contains_post_data(db_session):
    job = await _make_job_with_post(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/export/posts.csv")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "hello world" in resp.text
    assert "post_url" in resp.text.splitlines()[0]


async def test_export_md_contains_post_data(db_session):
    job = await _make_job_with_post(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/export/posts.md")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "hello world" in resp.text
    assert "| post_url |" in resp.text
