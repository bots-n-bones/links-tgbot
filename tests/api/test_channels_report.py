from starlette.testclient import TestClient

from api.main import app
from db.models import (
    ChannelParseJob,
    ChannelParseJobStatus,
    ChannelVoiceReport,
    ChannelVoiceReportStatus,
)


async def _make_job_with_report(db_session, *, report_status=ChannelVoiceReportStatus.done):
    job = ChannelParseJob(
        channel_username="testchannel",
        params_json={"post_limit": 10, "voice_dna": True},
        status=ChannelParseJobStatus.done,
        posts_count=5,
        avg_views=250,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    report = ChannelVoiceReport(
        job_id=job.id,
        status=report_status,
        metrics_json={},
        post_analyses_json=[],
        profile_json={
            "confidence": 0.82,
            "style_consistency": 0.75,
            "structure_consistency": 0.65,
            "dominant_template": "single_block",
            "template_frequency": 0.6,
            "content_pillars": [],
        },
        chart_data_json={
            "chart_voice_radar": {"type": "radar", "data": {"labels": [], "datasets": []}}
        },
        report_sections_json={
            "summary": {
                "voice_identity": "A punchy, direct voice.",
                "tone_of_voice": "Blunt and warm.",
            },
            "structure": {"structural_dna": "Short paragraphs."},
            "content": {"lexical_profile": "Plain English."},
            "insights": {
                "key_insights": ["Insight one", "Insight two"],
                "hidden_patterns": [],
                "under_the_hood": {"cheat_code": "Keep it short."},
                "recommendations": ["Do X"],
            },
        },
        report_md="# Voice DNA Report\n\nSome content.",
        confidence=0.82,
    )
    db_session.add(report)
    await db_session.commit()
    return job, report


async def test_report_page_renders_all_four_tabs(db_session):
    job, _report = await _make_job_with_report(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/report")

    assert resp.status_code == 200
    assert "① Summary" in resp.text
    assert "② Structure" in resp.text
    assert "③ Content" in resp.text
    assert "④ Insights" in resp.text
    assert "A punchy, direct voice." in resp.text
    assert "Insight one" in resp.text


async def test_report_page_includes_disclaimer(db_session):
    job, _report = await _make_job_with_report(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/report")

    assert "субъективная оценка алгоритма" in resp.text


async def test_report_page_kpi_hero_shows_consistency_scores_and_posts_count(db_session):
    job, _report = await _make_job_with_report(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/report")

    assert "75%" in resp.text  # style_consistency
    assert "65%" in resp.text  # structure_consistency
    assert "250" in resp.text


async def test_report_page_serializes_chart_data_as_json(db_session):
    job, _report = await _make_job_with_report(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/report")

    assert '"chart_voice_radar"' in resp.text
    assert 'id="chart-data"' in resp.text


async def test_report_page_shows_unavailable_state_when_report_failed(db_session):
    job, _report = await _make_job_with_report(
        db_session, report_status=ChannelVoiceReportStatus.failed
    )

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/report")

    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()
    assert "① Summary" not in resp.text


async def test_report_page_shows_unavailable_state_when_no_report_yet(db_session):
    job = ChannelParseJob(channel_username="testchannel", params_json={"post_limit": 10})
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/report")

    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


async def test_report_page_404_for_missing_job(db_session):
    with TestClient(app) as client:
        resp = client.get("/channels/parse/999999/report")
    assert resp.status_code == 404


async def test_export_report_md(db_session):
    job, _report = await _make_job_with_report(db_session)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/export/report.md")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "Voice DNA Report" in resp.text


async def test_export_report_md_404_when_missing(db_session):
    job = ChannelParseJob(channel_username="testchannel", params_json={"post_limit": 10})
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    with TestClient(app) as client:
        resp = client.get(f"/channels/parse/{job.id}/export/report.md")

    assert resp.status_code == 404
