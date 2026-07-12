from datetime import UTC, date, datetime

import worker.tasks as tasks_module
from db.models import ChannelParsedPost, ChannelParseJob, ChannelParseJobStatus, RawMessage
from sqlalchemy import select
from worker.channel_scraper import ChannelPreview, ChannelScrapeError, ScrapedPost


async def _make_job(db_session, **params) -> ChannelParseJob:
    job = ChannelParseJob(
        channel_username="testchannel",
        params_json={"post_limit": 10, **params},
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


def _fake_post(message_id: int, *, urls=None, views=100) -> ScrapedPost:
    return ScrapedPost(
        message_id=message_id,
        post_url=f"https://t.me/testchannel/{message_id}",
        text=f"post {message_id}",
        published_at=datetime(2026, 7, 1, tzinfo=UTC),
        views=views,
        urls_in_post=urls or [],
    )


async def test_job_completes_without_voice_dna(db_session, monkeypatch):
    job = await _make_job(db_session, voice_dna=False)

    async def fake_validate(username):
        return ChannelPreview(username=username, title="Test Channel", avatar_url=None, subscribers=100)

    async def fake_scrape(username, **kwargs):
        if kwargs.get("on_progress"):
            await kwargs["on_progress"](2, 10)
        return [_fake_post(1), _fake_post(2)]

    monkeypatch.setattr(tasks_module, "validate_channel", fake_validate)
    monkeypatch.setattr(tasks_module, "scrape_channel_posts", fake_scrape)

    await tasks_module._run_channel_parse_job_async(job.id)

    await db_session.refresh(job)
    assert job.status == ChannelParseJobStatus.done
    assert job.channel_title == "Test Channel"
    assert job.posts_count == 2
    assert job.avg_views == 100
    assert job.finished_at is not None

    posts = (
        (await db_session.execute(select(ChannelParsedPost).where(ChannelParsedPost.job_id == job.id)))
        .scalars()
        .all()
    )
    assert len(posts) == 2


async def test_job_triggers_voice_dna_analysis_task(db_session, monkeypatch):
    job = await _make_job(db_session, voice_dna=True)

    async def fake_validate(username):
        return ChannelPreview(username=username, title="Test Channel", avatar_url=None, subscribers=100)

    async def fake_scrape(username, **kwargs):
        return [_fake_post(1)]

    delay_calls = []
    monkeypatch.setattr(tasks_module, "validate_channel", fake_validate)
    monkeypatch.setattr(tasks_module, "scrape_channel_posts", fake_scrape)
    monkeypatch.setattr(
        tasks_module.analyze_channel_voice_dna, "delay", lambda job_id: delay_calls.append(job_id)
    )

    await tasks_module._run_channel_parse_job_async(job.id)

    await db_session.refresh(job)
    assert delay_calls == [job.id]
    # analyze_channel_voice_dna (мокнут) ещё не выполнялся -> job остаётся analyzing
    assert job.status == ChannelParseJobStatus.analyzing


async def test_job_fails_when_channel_invalid(db_session, monkeypatch):
    job = await _make_job(db_session)

    async def fake_validate(username):
        raise ChannelScrapeError(f"Channel @{username} not found or private")

    monkeypatch.setattr(tasks_module, "validate_channel", fake_validate)

    await tasks_module._run_channel_parse_job_async(job.id)

    await db_session.refresh(job)
    assert job.status == ChannelParseJobStatus.failed
    assert "not found" in job.error_message
    assert job.finished_at is not None


async def test_job_fails_when_scrape_raises(db_session, monkeypatch):
    job = await _make_job(db_session)

    async def fake_validate(username):
        return ChannelPreview(username=username, title="Test Channel", avatar_url=None, subscribers=100)

    async def fake_scrape(username, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks_module, "validate_channel", fake_validate)
    monkeypatch.setattr(tasks_module, "scrape_channel_posts", fake_scrape)

    await tasks_module._run_channel_parse_job_async(job.id)

    await db_session.refresh(job)
    assert job.status == ChannelParseJobStatus.failed
    assert "scrape failed" in job.error_message


async def test_job_computes_date_range_from_posts(db_session, monkeypatch):
    job = await _make_job(db_session, voice_dna=False)

    async def fake_validate(username):
        return ChannelPreview(username=username, title="Test Channel", avatar_url=None, subscribers=100)

    posts = [
        ScrapedPost(
            message_id=1,
            post_url="https://t.me/testchannel/1",
            text="a",
            published_at=datetime(2026, 6, 1, tzinfo=UTC),
            views=10,
        ),
        ScrapedPost(
            message_id=2,
            post_url="https://t.me/testchannel/2",
            text="b",
            published_at=datetime(2026, 6, 15, tzinfo=UTC),
            views=20,
        ),
    ]

    async def fake_scrape(username, **kwargs):
        return posts

    monkeypatch.setattr(tasks_module, "validate_channel", fake_validate)
    monkeypatch.setattr(tasks_module, "scrape_channel_posts", fake_scrape)

    await tasks_module._run_channel_parse_job_async(job.id)

    await db_session.refresh(job)
    assert job.date_range_from == date(2026, 6, 1)
    assert job.date_range_to == date(2026, 6, 15)
    assert job.avg_views == 15


async def test_collect_urls_enqueues_link_processing(db_session, monkeypatch):
    job = await _make_job(db_session, voice_dna=False, collect_urls=True)

    async def fake_validate(username):
        return ChannelPreview(username=username, title="Test Channel", avatar_url=None, subscribers=100)

    async def fake_scrape(username, **kwargs):
        return [_fake_post(1, urls=["https://example.com/a", "https://example.com/b"])]

    enqueued = []
    monkeypatch.setattr(tasks_module, "validate_channel", fake_validate)
    monkeypatch.setattr(tasks_module, "scrape_channel_posts", fake_scrape)
    monkeypatch.setattr(tasks_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    await tasks_module._run_channel_parse_job_async(job.id)

    assert len(enqueued) == 2
    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert {r.text for r in rows} == {"https://example.com/a", "https://example.com/b"}
    assert all(r.source_type.value == "manual" for r in rows)


async def test_collect_urls_is_deterministic_per_channel():
    id_a = tasks_module._channel_url_chat_id("testchannel")
    id_b = tasks_module._channel_url_chat_id("testchannel")
    id_c = tasks_module._channel_url_chat_id("otherchannel")
    assert id_a == id_b
    assert id_a != id_c


async def test_analyze_channel_voice_dna_marks_job_done(db_session):
    job = await _make_job(db_session)
    job.status = ChannelParseJobStatus.analyzing
    await db_session.commit()

    await tasks_module._analyze_channel_voice_dna_async(job.id)

    await db_session.refresh(job)
    assert job.status == ChannelParseJobStatus.done
    assert job.finished_at is not None
