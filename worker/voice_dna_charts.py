"""Chart.js-ready данные для Voice DNA отчёта (TZ_CHANNELS.md §7.4, §22).

13 графиков, по одному ключу на каждый chart_* ID из §3.5. Вход — уже
посчитанные stylometry.MetricsJson, список PostVoiceAnalysis (в порядке
постов) и агрегированный VoiceDnaProfile.
"""

from collections import Counter

from worker.stylometry import MetricsJson
from worker.voice_dna_models import PostVoiceAnalysis, VoiceDnaProfile

HOOK_ORDER = [
    "rhetorical_question",
    "bold_claim",
    "personal_anecdote",
    "number_stat",
    "scene_setting",
    "quote",
    "direct_address",
    "none",
]
WORD_COUNT_BUCKETS = [(0, 50), (50, 100), (100, 200), (200, 400), (400, None)]
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _distribution(values: list[str]) -> tuple[list[str], list[int]]:
    counts = Counter(values)
    labels = sorted(counts, key=lambda k: -counts[k])
    return labels, [counts[label] for label in labels]


def _bucket_word_counts(word_counts: list[int]) -> tuple[list[str], list[int]]:
    labels = []
    data = []
    for lo, hi in WORD_COUNT_BUCKETS:
        label = f"{lo}-{hi}" if hi is not None else f"{lo}+"
        labels.append(label)
        data.append(sum(1 for w in word_counts if w >= lo and (hi is None or w < hi)))
    return labels, data


def build_chart_data(
    metrics: MetricsJson, post_analyses: list[PostVoiceAnalysis], profile: VoiceDnaProfile
) -> dict:
    radar = profile.radar or metrics.radar
    radar_labels = ["Rhythm", "Specificity", "Register", "Structure", "Rhetoric", "Engagement"]
    radar_keys = ["rhythm", "specificity", "register", "structure", "rhetoric", "engagement"]

    hook_labels, hook_data = _distribution([a.hook_type for a in post_analyses])
    close_labels, close_data = _distribution([a.close_type for a in post_analyses])
    persona_counter: Counter[str] = Counter()
    for analysis in post_analyses:
        persona_counter.update(analysis.persona_markers)
    total_persona = sum(persona_counter.values()) or 1

    ethos = pathos = logos = 0.0
    if post_analyses:
        ethos = sum(a.ethos_pathos_logos.get("ethos", 0.0) for a in post_analyses) / len(
            post_analyses
        )
        pathos = sum(a.ethos_pathos_logos.get("pathos", 0.0) for a in post_analyses) / len(
            post_analyses
        )
        logos = sum(a.ethos_pathos_logos.get("logos", 0.0) for a in post_analyses) / len(
            post_analyses
        )

    length_labels, length_data = _bucket_word_counts(metrics.post_word_counts)

    hook_ordinal = {hook: i for i, hook in enumerate(HOOK_ORDER)}
    scatter_points = [
        {"x": hook_ordinal.get(a.hook_type, len(HOOK_ORDER) - 1), "y": v}
        for a, v in zip(post_analyses, metrics.post_views, strict=False)
        if v is not None
    ]

    return {
        "chart_voice_radar": {
            "type": "radar",
            "data": {
                "labels": radar_labels,
                "datasets": [
                    {"label": "Voice DNA", "data": [radar.get(k, 0.0) for k in radar_keys]}
                ],
            },
            "options": {"scales": {"r": {"min": 0, "max": 100}}},
        },
        "chart_tone_bars": {
            "type": "bar",
            "data": {
                "labels": [
                    "Funny←→Serious",
                    "Formal←→Casual",
                    "Respect←→Irreverent",
                    "Enthusiastic←→Matter-of-fact",
                ],
                "datasets": [
                    {
                        "data": [
                            profile.tone_dimensions.get("funny_serious", 0.0),
                            profile.tone_dimensions.get("formal_casual", 0.0),
                            profile.tone_dimensions.get("respectful_irreverent", 0.0),
                            profile.tone_dimensions.get("enthusiastic_matter_of_fact", 0.0),
                        ]
                    }
                ],
            },
            "options": {"indexAxis": "y", "scales": {"x": {"min": 0, "max": 100}}},
        },
        "chart_hook_donut": {
            "type": "doughnut",
            "data": {"labels": hook_labels, "datasets": [{"data": hook_data}]},
        },
        "chart_length_histogram": {
            "type": "bar",
            "data": {"labels": length_labels, "datasets": [{"data": length_data}]},
        },
        "chart_sentence_rhythm": {
            "type": "bar",
            "data": {
                "labels": [str(i + 1) for i in range(len(metrics.post_sentence_avgs))],
                "datasets": [{"label": "Avg sentence length", "data": metrics.post_sentence_avgs}],
            },
            "options": {"slv": metrics.slv},
        },
        "chart_close_bars": {
            "type": "bar",
            "data": {"labels": close_labels, "datasets": [{"data": close_data}]},
        },
        "chart_rhetoric_triangle": {
            "type": "bar",
            "data": {
                "labels": ["Ethos", "Pathos", "Logos"],
                "datasets": [{"data": [ethos * 100, pathos * 100, logos * 100]}],
            },
            "options": {"stacked": True},
        },
        "chart_pillars": {
            "type": "bar",
            "data": {
                "labels": [p.topic for p in profile.content_pillars],
                "datasets": [{"data": [p.share * 100 for p in profile.content_pillars]}],
            },
            "options": {"indexAxis": "y"},
        },
        "chart_transitions": {
            "type": "bar",
            "data": {
                "labels": [t["transition"] for t in metrics.transition_fingerprint],
                "datasets": [{"data": [t["count"] for t in metrics.transition_fingerprint]}],
            },
        },
        "chart_views_scatter": {
            "type": "scatter",
            "data": {"datasets": [{"label": "Views by hook type", "data": scatter_points}]},
            "options": {"hook_labels": HOOK_ORDER},
        },
        "chart_cadence_heatmap": {
            "type": "bar",
            "data": {
                "labels": WEEKDAY_LABELS,
                "datasets": [
                    {
                        "label": "Posts by weekday",
                        "data": [metrics.weekday_distribution.get(k, 0) for k in WEEKDAY_KEYS],
                    }
                ],
            },
            "options": {"monthly": metrics.monthly_distribution},
        },
        "chart_emoji_gauges": {
            "type": "doughnut",
            "data": {
                "labels": [e["emoji"] for e in metrics.emoji_top],
                "datasets": [{"data": [e["count"] for e in metrics.emoji_top]}],
            },
            "options": {"emoji_per_100_words": metrics.emoji_per_100_words},
        },
        "chart_persona_bars": {
            "type": "bar",
            "data": {
                "labels": list(persona_counter.keys()),
                "datasets": [
                    {
                        "data": [count / total_persona * 100 for count in persona_counter.values()],
                    }
                ],
            },
        },
    }
