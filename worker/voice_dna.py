"""Voice DNA оркестрация (TZ_CHANNELS.md §7.1) — вызывается из
worker.tasks.analyze_channel_voice_dna, когда params_json["voice_dna"]=true.

Если LLM-этап падает, посты (волна D) остаются доступны — job всё равно
переходит в done, а ChannelVoiceReport.status=failed фиксирует причину
(тот же "soft-fail, не роняем job" паттерн, что и в channel_scraper.py).
"""

import logging
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select

from db.models import (
    ChannelParsedPost,
    ChannelParseJob,
    ChannelParseJobStatus,
    ChannelVoiceReport,
    ChannelVoiceReportStatus,
)
from db.session import get_sessionmaker
from shared.config import get_settings
from worker.llm import get_llm_client
from worker.stylometry import MetricsJson, compute_metrics
from worker.voice_dna_charts import build_chart_data
from worker.voice_dna_models import PostVoiceAnalysis, ReportSections, VoiceDnaProfile

logger = logging.getLogger(__name__)

MAX_POST_TEXT_CHARS = 1500


def _truncate(text: str | None) -> str:
    return (text or "")[:MAX_POST_TEXT_CHARS]


async def classify_posts_batch(
    posts: list[ChannelParsedPost], *, model: str
) -> list[PostVoiceAnalysis]:
    settings = get_settings()
    client = get_llm_client()
    results: list[PostVoiceAnalysis] = []
    for i in range(0, len(posts), settings.voice_dna_batch_size):
        batch = posts[i : i + settings.voice_dna_batch_size]
        payload = [{"post_id": p.id, "text": _truncate(p.text)} for p in batch]
        batch_result = await client.classify_posts_batch(posts=payload, model=model)
        by_id = {item.post_id: item for item in batch_result.items}
        for post in batch:
            results.append(by_id.get(post.id, PostVoiceAnalysis(post_id=post.id)))
    return results


def _mode_share(values: list[str]) -> tuple[str, float]:
    filtered = [v for v in values if v]
    if not filtered:
        return "", 0.0
    counter = Counter(filtered)
    mode, count = counter.most_common(1)[0]
    return mode, count / len(filtered)


def compute_deterministic_profile_fields(post_analyses: list[PostVoiceAnalysis]) -> dict:
    """style_consistency/structure_consistency/dominant_template/template_frequency
    computed from post_analyses instead of guessed by the LLM. Previously the
    LLM invented a single "confidence" score and a "template_frequency" that
    regularly contradicted its own generated prose (e.g. writing "the voice
    profile is undetermined" for a channel whose actual per-post data was
    highly consistent) — these are measurable, so we measure them."""
    _, register_share = _mode_share([a.register for a in post_analyses])
    _, punctuation_share = _mode_share([a.punctuation_style for a in post_analyses])
    style_consistency = (register_share + punctuation_share) / 2

    dominant_template, template_frequency = _mode_share(
        [a.body_structure for a in post_analyses]
    )
    _, hook_share = _mode_share([a.hook_type for a in post_analyses])
    _, close_share = _mode_share([a.close_type for a in post_analyses])
    structure_consistency = (template_frequency + hook_share + close_share) / 3

    return {
        "style_consistency": style_consistency,
        "structure_consistency": structure_consistency,
        "dominant_template": dominant_template,
        "template_frequency": template_frequency,
    }


def _merge_radar(metrics_radar: dict, profile_radar: dict) -> dict:
    """rhythm/specificity — детерминированные (stylometry.py), остальные 4
    оси — из LLM-агрегации (§6.2 примечание)."""
    return {
        "rhythm": metrics_radar.get("rhythm", 0.0),
        "specificity": metrics_radar.get("specificity", 0.0),
        "register": profile_radar.get("register", 0.0),
        "structure": profile_radar.get("structure", 0.0),
        "rhetoric": profile_radar.get("rhetoric", 0.0),
        "engagement": profile_radar.get("engagement", 0.0),
    }


def render_report_markdown(
    sections: ReportSections, chart_data: dict, profile: VoiceDnaProfile
) -> str:
    lines = [
        f"# Voice DNA Report — {profile.voice_identity or 'Untitled channel'}",
        "",
        f"**Style consistency:** {profile.style_consistency:.2f}"
        f"  **Structure consistency:** {profile.structure_consistency:.2f}",
        f"**Dominant template:** {profile.dominant_template} ({profile.template_frequency:.0%})",
        "",
        "## Summary",
        "",
        sections.summary.tone_of_voice,
        "",
        sections.summary.successful_formats,
        "",
        "## Structure",
        "",
        sections.structure.structural_dna,
        "",
        sections.structure.rhythm_analysis,
        "",
        "## Content",
        "",
        sections.content.lexical_profile,
        "",
        sections.content.rhetoric_strategy,
        "",
        "## Insights",
        "",
        *[f"- {insight}" for insight in sections.insights.key_insights],
        "",
        "### Recommendations",
        "",
        *[f"- {rec}" for rec in sections.insights.recommendations],
        "",
    ]
    return "\n".join(lines) + "\n"


async def _fail_report(sessionmaker, job_id: int) -> None:
    async with sessionmaker() as session:
        job = await session.get(ChannelParseJob, job_id)
        if job is None:
            return
        session.add(ChannelVoiceReport(job_id=job_id, status=ChannelVoiceReportStatus.failed))
        job.status = ChannelParseJobStatus.done
        job.finished_at = datetime.now(UTC)
        await session.commit()


async def analyze_voice_dna(job_id: int) -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        job = await session.get(ChannelParseJob, job_id)
        if job is None:
            return
        posts = list(
            (
                await session.execute(
                    select(ChannelParsedPost)
                    .where(ChannelParsedPost.job_id == job_id)
                    .order_by(ChannelParsedPost.published_at)
                )
            )
            .scalars()
            .all()
        )

    if not posts:
        await _fail_report(sessionmaker, job_id)
        return

    try:
        client = get_llm_client()
        metrics: MetricsJson = compute_metrics(posts)
        post_analyses = await classify_posts_batch(posts, model=settings.openai_model_mini)
        deterministic_fields = compute_deterministic_profile_fields(post_analyses)

        # style_consistency/structure_consistency go into <metrics> (the tag
        # the prompt is told to never contradict) so the aggregate call's own
        # prose is grounded in them from the start, not just overridden after.
        aggregate_metrics = metrics.model_dump()
        aggregate_metrics["style_consistency"] = deterministic_fields["style_consistency"]
        aggregate_metrics["structure_consistency"] = deterministic_fields["structure_consistency"]

        sample_posts = [p.text or "" for p in posts[: settings.voice_dna_sample_posts]]
        profile = await client.aggregate_voice_profile(
            metrics=aggregate_metrics,
            post_analyses=[a.model_dump() for a in post_analyses],
            sample_posts=sample_posts,
            language=settings.voice_dna_report_language,
            model=settings.openai_model_report,
        )
        profile.radar = _merge_radar(metrics.radar, profile.radar)
        profile.style_consistency = deterministic_fields["style_consistency"]
        profile.structure_consistency = deterministic_fields["structure_consistency"]
        profile.dominant_template = deterministic_fields["dominant_template"]
        profile.template_frequency = deterministic_fields["template_frequency"]
        profile.confidence = (profile.style_consistency + profile.structure_consistency) / 2

        chart_data = build_chart_data(metrics, post_analyses, profile)
        chart_summary = ", ".join(chart_data.keys())

        sections = await client.generate_report_sections(
            profile=profile.model_dump(),
            metrics=metrics.model_dump(),
            chart_summary=chart_summary,
            language=settings.voice_dna_report_language,
            model=settings.openai_model_report,
        )
        # profile.voice_identity (aggregate call: full metrics + post_analyses
        # + sample_posts context) is the single source of truth — the sections
        # call re-derives its own from a narrower prompt and the two could
        # otherwise disagree on-screen.
        sections.summary.voice_identity = profile.voice_identity
        report_md = render_report_markdown(sections, chart_data, profile)
    except Exception:
        logger.exception("Voice DNA analysis failed for job %s", job_id)
        await _fail_report(sessionmaker, job_id)
        return

    async with sessionmaker() as session:
        job = await session.get(ChannelParseJob, job_id)
        if job is None:
            return
        session.add(
            ChannelVoiceReport(
                job_id=job_id,
                status=ChannelVoiceReportStatus.done,
                metrics_json=metrics.model_dump(),
                post_analyses_json=[a.model_dump() for a in post_analyses],
                profile_json=profile.model_dump(),
                chart_data_json=chart_data,
                report_sections_json=sections.model_dump(),
                report_md=report_md,
                confidence=profile.confidence,
                model=settings.openai_model_report,
            )
        )
        job.status = ChannelParseJobStatus.done
        job.finished_at = datetime.now(UTC)
        await session.commit()
