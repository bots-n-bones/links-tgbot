from datetime import UTC, datetime

from sqlalchemy import select

from db.models import (
    ChannelParsedPost,
    ChannelParseJob,
    ChannelParseJobStatus,
    ChannelVoiceReport,
    ChannelVoiceReportStatus,
)
from worker.stylometry import compute_metrics
from worker.voice_dna import (
    _merge_radar,
    analyze_voice_dna,
    compute_deterministic_profile_fields,
    render_report_markdown,
)
from worker.voice_dna_charts import build_chart_data
from worker.voice_dna_models import (
    PostVoiceAnalysis,
    ReportSections,
    VoiceDnaProfile,
)


def _post(message_id: int, text: str, **kwargs) -> ChannelParsedPost:
    defaults = dict(
        job_id=1,
        message_id=message_id,
        post_url=f"https://t.me/testchannel/{message_id}",
        published_at=datetime(2026, 7, message_id, tzinfo=UTC),
        views=100 * message_id,
    )
    defaults.update(kwargs)
    return ChannelParsedPost(text=text, **defaults)


def test_merge_radar_prefers_stylometry_for_rhythm_and_specificity():
    merged = _merge_radar(
        {"rhythm": 80.0, "specificity": 70.0},
        {"register": 60.0, "structure": 50.0, "rhetoric": 40.0, "engagement": 30.0},
    )
    assert merged == {
        "rhythm": 80.0,
        "specificity": 70.0,
        "register": 60.0,
        "structure": 50.0,
        "rhetoric": 40.0,
        "engagement": 30.0,
    }


def test_build_chart_data_returns_all_13_chart_ids():
    posts = [_post(1, "Is this real? So exciting!"), _post(2, "A bold claim about the future.")]
    metrics = compute_metrics(posts)
    analyses = [
        PostVoiceAnalysis(
            post_id=1,
            hook_type="rhetorical_question",
            close_type="cta_question",
            ethos_pathos_logos={"ethos": 0.2, "pathos": 0.5, "logos": 0.3},
            persona_markers=["direct_you"],
        ),
        PostVoiceAnalysis(
            post_id=2,
            hook_type="bold_claim",
            close_type="summary",
            ethos_pathos_logos={"ethos": 0.4, "pathos": 0.2, "logos": 0.4},
            persona_markers=["we_inclusive"],
        ),
    ]
    profile = VoiceDnaProfile(
        radar={
            "rhythm": 70,
            "specificity": 60,
            "register": 50,
            "structure": 40,
            "rhetoric": 30,
            "engagement": 20,
        },
        tone_dimensions={
            "funny_serious": 30,
            "formal_casual": 70,
            "respectful_irreverent": 50,
            "enthusiastic_matter_of_fact": 60,
        },
    )

    charts = build_chart_data(metrics, analyses, profile)

    expected_ids = {
        "chart_voice_radar",
        "chart_tone_bars",
        "chart_hook_donut",
        "chart_length_histogram",
        "chart_sentence_rhythm",
        "chart_close_bars",
        "chart_rhetoric_triangle",
        "chart_pillars",
        "chart_transitions",
        "chart_views_scatter",
        "chart_cadence_heatmap",
        "chart_emoji_gauges",
        "chart_persona_bars",
    }
    assert set(charts.keys()) == expected_ids
    assert charts["chart_voice_radar"]["data"]["datasets"][0]["data"] == [70, 60, 50, 40, 30, 20]
    assert charts["chart_hook_donut"]["data"]["labels"] == ["rhetorical_question", "bold_claim"]


def test_render_report_markdown_includes_key_sections():
    sections = ReportSections()
    sections.summary.tone_of_voice = "Direct and punchy."
    sections.insights.key_insights = ["Insight one"]
    profile = VoiceDnaProfile(
        voice_identity="A test channel voice", style_consistency=0.8, structure_consistency=0.7
    )

    md = render_report_markdown(sections, {}, profile)

    assert "A test channel voice" in md
    assert "Direct and punchy." in md
    assert "- Insight one" in md
    assert "0.80" in md
    assert "0.70" in md


def test_compute_deterministic_profile_fields_perfectly_consistent():
    analyses = [
        PostVoiceAnalysis(
            post_id=i,
            register="conversational",
            punctuation_style="minimal",
            body_structure="single_block",
            hook_type="bold_claim",
            close_type="summary",
        )
        for i in range(1, 4)
    ]

    fields = compute_deterministic_profile_fields(analyses)

    assert fields["style_consistency"] == 1.0
    assert fields["structure_consistency"] == 1.0
    assert fields["dominant_template"] == "single_block"
    assert fields["template_frequency"] == 1.0


def test_compute_deterministic_profile_fields_mixed_styles():
    analyses = [
        PostVoiceAnalysis(post_id=1, register="conversational", body_structure="single_block"),
        PostVoiceAnalysis(post_id=2, register="formal", body_structure="single_block"),
        PostVoiceAnalysis(post_id=3, register="formal", body_structure="bullet_list"),
    ]

    fields = compute_deterministic_profile_fields(analyses)

    assert fields["dominant_template"] == "single_block"
    assert fields["template_frequency"] == 2 / 3
    assert 0.0 < fields["style_consistency"] < 1.0


def test_compute_deterministic_profile_fields_empty_input():
    fields = compute_deterministic_profile_fields([])
    assert fields == {
        "style_consistency": 0.0,
        "structure_consistency": 0.0,
        "dominant_template": "",
        "template_frequency": 0.0,
    }


async def test_analyze_voice_dna_creates_report_and_marks_job_done(db_session, workspace_id):
    job = ChannelParseJob(
        workspace_id=workspace_id, channel_username="testchannel", params_json={"post_limit": 10}
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
                text="Hello world, this is a post.",
                published_at=datetime(2026, 7, 1, tzinfo=UTC),
                views=100,
            ),
            ChannelParsedPost(
                job_id=job.id,
                message_id=2,
                post_url="https://t.me/testchannel/2",
                text="Another post with more words in it than the first one did.",
                published_at=datetime(2026, 7, 2, tzinfo=UTC),
                views=200,
            ),
        ]
    )
    await db_session.commit()

    await analyze_voice_dna(job.id)

    await db_session.refresh(job)
    assert job.status == ChannelParseJobStatus.done
    assert job.finished_at is not None

    report = (
        await db_session.execute(
            select(ChannelVoiceReport).where(ChannelVoiceReport.job_id == job.id)
        )
    ).scalar_one()
    assert report.status == ChannelVoiceReportStatus.done
    assert report.metrics_json is not None
    assert report.chart_data_json is not None
    assert len(report.post_analyses_json) == 2
    assert report.report_md

    # style_consistency/structure_consistency/dominant_template/template_frequency
    # are computed in Python from post_analyses, not trusted from the LLM.
    profile = report.profile_json
    assert profile["dominant_template"] == "single_block"
    assert profile["template_frequency"] == 1.0
    assert profile["style_consistency"] == 1.0
    assert 0.0 <= profile["structure_consistency"] <= 1.0
    assert (
        profile["confidence"]
        == (profile["style_consistency"] + profile["structure_consistency"]) / 2
    )

    # single source of truth: the sections call's own voice_identity guess is
    # discarded in favor of the aggregate profile's.
    assert report.report_sections_json["summary"]["voice_identity"] == profile["voice_identity"]


async def test_analyze_voice_dna_marks_report_failed_when_no_posts(db_session, workspace_id):
    job = ChannelParseJob(
        workspace_id=workspace_id, channel_username="emptychannel", params_json={"post_limit": 10}
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    await analyze_voice_dna(job.id)

    await db_session.refresh(job)
    assert job.status == ChannelParseJobStatus.done

    report = (
        await db_session.execute(
            select(ChannelVoiceReport).where(ChannelVoiceReport.job_id == job.id)
        )
    ).scalar_one()
    assert report.status == ChannelVoiceReportStatus.failed
