from datetime import UTC, datetime

from db.models import ChannelParsedPost
from worker.stylometry import compute_metrics


def _post(text: str, **kwargs) -> ChannelParsedPost:
    defaults = dict(job_id=1, message_id=1, post_url="https://t.me/x/1")
    defaults.update(kwargs)
    return ChannelParsedPost(text=text, **defaults)


def test_slv_zero_for_uniform_sentence_lengths():
    # every sentence has exactly 4 words -> zero variance
    text = "one two three four. five six seven eight. nine ten eleven twelve."
    metrics = compute_metrics([_post(text)])
    assert metrics.slv == 0.0


def test_slv_positive_for_varied_sentence_lengths():
    text = "short one. this sentence has quite a few more words in it than the other one."
    metrics = compute_metrics([_post(text)])
    assert metrics.slv > 0.0


def test_short_and_long_sentence_ratios():
    text = "hi there friend. " + " ".join(["word"] * 30) + "."
    metrics = compute_metrics([_post(text)])
    assert metrics.short_sentence_ratio == 0.5
    assert metrics.long_sentence_ratio == 0.5


def test_transition_fingerprint_counts_sentence_starts():
    text = "So here we go. So here we start. Something else entirely different."
    metrics = compute_metrics([_post(text)])
    top = metrics.transition_fingerprint[0]
    assert top["transition"] == "so here we"
    assert top["count"] == 2


def test_vsr_score_prefers_concrete_words():
    concrete_text = "table chair car house phone"
    metrics = compute_metrics([_post(concrete_text)])
    assert metrics.vsr_score == 1.0


def test_vsr_score_zero_for_abstract_words():
    abstract_text = "freedom justice truth belief theory"
    metrics = compute_metrics([_post(abstract_text)])
    assert metrics.vsr_score == 0.0


def test_emoji_counted_and_ranked():
    metrics = compute_metrics([_post("great news 🔥🔥🔥 love it 🎉")])
    assert metrics.emoji_top[0]["emoji"] == "🔥"
    assert metrics.emoji_top[0]["count"] == 3


def test_exclamation_and_question_ratios():
    posts = [_post("Wow!"), _post("Is this real?"), _post("Just a statement.")]
    metrics = compute_metrics(posts)
    assert metrics.exclamation_ratio == 1 / 3
    assert metrics.question_end_ratio == 1 / 3


def test_list_post_detected():
    list_text = "Here is my list:\n- first item\n- second item\n- third item"
    metrics = compute_metrics([_post(list_text), _post("no list here at all")])
    assert metrics.list_post_ratio == 0.5


def test_links_per_post_uses_urls_in_post_field():
    metrics = compute_metrics(
        [
            _post("check this out", urls_in_post=["https://a.com", "https://b.com"]),
            _post("nothing here"),
        ]
    )
    assert metrics.links_per_post == 1.0


def test_weekday_and_monthly_distribution():
    posts = [
        _post("a", published_at=datetime(2026, 7, 6, tzinfo=UTC)),  # Monday
        _post("b", published_at=datetime(2026, 7, 7, tzinfo=UTC)),  # Tuesday
        _post("c", published_at=datetime(2026, 8, 3, tzinfo=UTC)),  # Monday
    ]
    metrics = compute_metrics(posts)
    assert metrics.weekday_distribution["mon"] == 2
    assert metrics.weekday_distribution["tue"] == 1
    assert metrics.monthly_distribution == {"2026-07": 2, "2026-08": 1}


def test_radar_has_placeholders_for_llm_fields():
    metrics = compute_metrics([_post("hello world")])
    assert metrics.radar["register_placeholder"] == 0.0
    assert metrics.radar["structure_placeholder"] == 0.0
    assert metrics.radar["rhetoric_placeholder"] == 0.0
    assert metrics.radar["engagement"] == 0.0
    assert 0.0 <= metrics.radar["rhythm"] <= 100.0
    assert 0.0 <= metrics.radar["specificity"] <= 100.0


def test_empty_post_list_does_not_crash():
    metrics = compute_metrics([])
    assert metrics.avg_words == 0.0
    assert metrics.vsr_score == 0.0
    assert metrics.top_words == []
