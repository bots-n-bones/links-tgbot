from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import (
    ChannelParsedPost,
    ChannelParseJob,
    ChannelParseJobStatus,
    ChannelVoiceReport,
    ChannelVoiceReportStatus,
)


async def _make_job(db_session, **kwargs) -> ChannelParseJob:
    defaults = dict(channel_username="somechannel", params_json={"post_limit": 50})
    defaults.update(kwargs)
    job = ChannelParseJob(**defaults)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


async def test_job_defaults_to_pending_status(db_session):
    job = await _make_job(db_session)
    assert job.status == ChannelParseJobStatus.pending
    assert job.progress_current == 0
    assert job.posts_count == 0


async def test_parsed_post_unique_per_job_and_message(db_session):
    job = await _make_job(db_session)
    db_session.add(
        ChannelParsedPost(
            job_id=job.id,
            message_id=100,
            post_url="https://t.me/somechannel/100",
            published_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    db_session.add(
        ChannelParsedPost(
            job_id=job.id,
            message_id=100,
            post_url="https://t.me/somechannel/100",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_deleting_job_cascades_to_posts_and_report(db_session):
    job = await _make_job(db_session)
    db_session.add(
        ChannelParsedPost(job_id=job.id, message_id=1, post_url="https://t.me/somechannel/1")
    )
    db_session.add(
        ChannelVoiceReport(job_id=job.id, status=ChannelVoiceReportStatus.pending)
    )
    await db_session.commit()

    await db_session.delete(job)
    await db_session.commit()

    posts = (await db_session.execute(select(ChannelParsedPost))).scalars().all()
    reports = (await db_session.execute(select(ChannelVoiceReport))).scalars().all()
    assert posts == []
    assert reports == []


async def test_voice_report_status_defaults_to_pending(db_session):
    job = await _make_job(db_session)
    report = ChannelVoiceReport(job_id=job.id)
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    assert report.status == ChannelVoiceReportStatus.pending
