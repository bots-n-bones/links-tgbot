"""Стилометрия канала — чистый Python, без LLM (TZ_CHANNELS.md §6).

register/structure/rhetoric/engagement в radar — плейсхолдеры (0.0),
заполняются после LLM-прохода в worker/voice_dna.py (волна F).
"""

import json
import re
import statistics
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from db.models import ChannelParsedPost

_VSR_WORDS_PATH = Path(__file__).parent / "data" / "vsr_words.json"
_VSR_WORDS = json.loads(_VSR_WORDS_PATH.read_text())
_CONCRETE_WORDS = {w.lower() for w in _VSR_WORDS["concrete"]}
_ABSTRACT_WORDS = {w.lower() for w in _VSR_WORDS["abstract"]}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9_]+")
_EMOJI_RE = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]")
_LIST_MARKER_RE = re.compile(r"^\s*([-•*]|\d+[.)])\s+", re.MULTILINE)
_URL_RE = re.compile(r"https?://\S+")

SHORT_SENTENCE_MAX_WORDS = 8
LONG_SENTENCE_MIN_WORDS = 25
TOP_EMOJI_COUNT = 10
TOP_WORDS_COUNT = 20
TOP_TRANSITIONS_COUNT = 15
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "is",
    "are",
    "was",
    "were",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "at",
    "by",
    "from",
    "this",
    "that",
    "it",
    "as",
    "be",
    "not",
    "и",
    "в",
    "не",
    "на",
    "с",
    "что",
    "как",
    "это",
    "но",
    "а",
    "по",
    "за",
    "к",
    "из",
    "то",
    "же",
    "у",
    "он",
    "она",
    "они",
    "мы",
    "вы",
    "я",
    "для",
    "от",
    "до",
    "или",
}

WEEKDAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class MetricsJson(BaseModel):
    avg_chars: float
    avg_words: float
    avg_sentences: float
    slv: float
    short_sentence_ratio: float
    long_sentence_ratio: float

    emoji_per_100_words: float
    emoji_top: list[dict]
    exclamation_ratio: float
    question_end_ratio: float
    caps_word_ratio: float
    list_post_ratio: float
    links_per_post: float

    vsr_score: float
    top_words: list[dict]
    transition_fingerprint: list[dict]

    post_word_counts: list[int]
    post_sentence_avgs: list[float]
    post_views: list[int | None]
    post_dates: list[str]

    posts_per_week: float
    weekday_distribution: dict[str, int]
    monthly_distribution: dict[str, int]

    radar: dict[str, float]


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s]


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _is_list_post(text: str) -> bool:
    return len(_LIST_MARKER_RE.findall(text)) >= 2


def _links_in_post(post: ChannelParsedPost) -> int:
    if post.urls_in_post:
        return len(post.urls_in_post)
    return len(_URL_RE.findall(post.text or ""))


def compute_metrics(posts: list[ChannelParsedPost]) -> MetricsJson:
    texts = [p.text or "" for p in posts]

    sentence_word_counts: list[int] = []
    sentence_starts: list[str] = []
    all_words: list[str] = []
    emoji_counter: Counter[str] = Counter()
    word_counter: Counter[str] = Counter()

    post_word_counts: list[int] = []
    post_sentence_avgs: list[float] = []

    exclamation_count = 0
    question_end_count = 0
    list_post_count = 0
    total_links = 0
    caps_word_count = 0

    for text in texts:
        sentences = _split_sentences(text)
        words = _words(text)
        all_words.extend(words)
        post_word_counts.append(len(words))

        sent_word_lens = []
        for sentence in sentences:
            sent_words = _words(sentence)
            sentence_word_counts.append(len(sent_words))
            sent_word_lens.append(len(sent_words))
            if sent_words:
                sentence_starts.append(" ".join(w.lower() for w in sent_words[:3]))
        post_sentence_avgs.append(statistics.fmean(sent_word_lens) if sent_word_lens else 0.0)

        for word in words:
            word_counter[word.lower()] += 1
            if len(word) >= 2 and word.isupper() and word.isalpha():
                caps_word_count += 1

        for emoji_char in _EMOJI_RE.findall(text):
            emoji_counter[emoji_char] += 1

        if "!" in text:
            exclamation_count += 1
        if text.strip().endswith("?"):
            question_end_count += 1
        if _is_list_post(text):
            list_post_count += 1

    for post in posts:
        total_links += _links_in_post(post)

    n_posts = len(posts) or 1
    total_sentences = len(sentence_word_counts) or 1
    total_words = len(all_words) or 1

    concrete_hits = sum(1 for w in all_words if w.lower() in _CONCRETE_WORDS)
    abstract_hits = sum(1 for w in all_words if w.lower() in _ABSTRACT_WORDS)
    vsr_score = (
        concrete_hits / (concrete_hits + abstract_hits) if (concrete_hits + abstract_hits) else 0.0
    )

    slv = statistics.pstdev(sentence_word_counts) if len(sentence_word_counts) > 1 else 0.0
    short_ratio = (
        sum(1 for c in sentence_word_counts if c <= SHORT_SENTENCE_MAX_WORDS) / total_sentences
    )
    long_ratio = (
        sum(1 for c in sentence_word_counts if c >= LONG_SENTENCE_MIN_WORDS) / total_sentences
    )

    top_words = [
        {"word": word, "count": count}
        for word, count in word_counter.most_common(TOP_WORDS_COUNT * 2)
        if word not in STOPWORDS and len(word) >= 3
    ][:TOP_WORDS_COUNT]

    transition_counter = Counter(sentence_starts)
    transition_fingerprint = [
        {"transition": t, "count": c}
        for t, c in transition_counter.most_common(TOP_TRANSITIONS_COUNT)
    ]

    emoji_top = [{"emoji": e, "count": c} for e, c in emoji_counter.most_common(TOP_EMOJI_COUNT)]

    post_views = [p.views for p in posts]
    post_dates = [p.published_at.date().isoformat() for p in posts if p.published_at]

    weekday_distribution = dict.fromkeys(WEEKDAY_NAMES, 0)
    monthly_distribution: dict[str, int] = {}
    for post in posts:
        if post.published_at is None:
            continue
        weekday_distribution[WEEKDAY_NAMES[post.published_at.weekday()]] += 1
        month_key = post.published_at.strftime("%Y-%m")
        monthly_distribution[month_key] = monthly_distribution.get(month_key, 0) + 1

    dated_posts = [p for p in posts if p.published_at]
    if len(dated_posts) >= 2:
        span_days = max(
            (
                max(p.published_at for p in dated_posts) - min(p.published_at for p in dated_posts)
            ).days,
            1,
        )
        posts_per_week = len(dated_posts) / (span_days / 7)
    else:
        posts_per_week = float(len(dated_posts))

    rhythm = max(0.0, min(100.0, 100.0 - slv * 4))
    specificity = max(0.0, min(100.0, vsr_score * 100))

    return MetricsJson(
        avg_chars=statistics.fmean(len(t) for t in texts) if texts else 0.0,
        avg_words=statistics.fmean(post_word_counts) if post_word_counts else 0.0,
        avg_sentences=statistics.fmean([len(_split_sentences(t)) for t in texts]) if texts else 0.0,
        slv=slv,
        short_sentence_ratio=short_ratio,
        long_sentence_ratio=long_ratio,
        emoji_per_100_words=(sum(emoji_counter.values()) / total_words) * 100,
        emoji_top=emoji_top,
        exclamation_ratio=exclamation_count / n_posts,
        question_end_ratio=question_end_count / n_posts,
        caps_word_ratio=caps_word_count / total_words,
        list_post_ratio=list_post_count / n_posts,
        links_per_post=total_links / n_posts,
        vsr_score=vsr_score,
        top_words=top_words,
        transition_fingerprint=transition_fingerprint,
        post_word_counts=post_word_counts,
        post_sentence_avgs=post_sentence_avgs,
        post_views=post_views,
        post_dates=post_dates,
        posts_per_week=posts_per_week,
        weekday_distribution=weekday_distribution,
        monthly_distribution=monthly_distribution,
        radar={
            "rhythm": rhythm,
            "specificity": specificity,
            "register_placeholder": 0.0,
            "structure_placeholder": 0.0,
            "rhetoric_placeholder": 0.0,
            "engagement": 0.0,
        },
    )
