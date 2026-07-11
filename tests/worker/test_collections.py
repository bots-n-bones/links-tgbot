from datetime import UTC, datetime, timedelta

import worker.collections as collections_module
from db.models import Link, LinkSource, LinkStatus, SourceType
from worker.llm import DigestArticle, DigestSelection
from worker.search import SearchResult


class FixedSearchClient:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.queries: list[str] = []

    async def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        return self.results[:max_results]


class FixedLLMClient:
    def __init__(self, articles: list[DigestArticle]) -> None:
        self.articles = articles
        self.calls: list[dict] = []

    async def select_digest_articles(self, *, system_prompt, user_prompt, model) -> DigestSelection:
        self.calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt, "model": model}
        )
        return DigestSelection(articles=self.articles)

    async def complete(self, **kwargs):
        raise NotImplementedError

    async def describe_link(self, **kwargs):
        raise NotImplementedError


async def _make_link_with_source(
    db_session, *, url, priority, created_days_ago, url_hash, is_hidden=False
):
    now = datetime.now(UTC) - timedelta(days=created_days_ago)
    link = Link(
        url=url,
        normalized_url=url,
        url_hash=url_hash,
        title=f"T {url}",
        status=LinkStatus.done,
        priority_score=priority,
        is_hidden=is_hidden,
        created_at=now,
    )
    db_session.add(link)
    await db_session.flush()
    db_session.add(
        LinkSource(link_id=link.id, sender_id=1, source_type=SourceType.group, created_at=now)
    )
    await db_session.commit()
    await db_session.refresh(link)
    return link


async def test_generate_daily_digest_returns_none_without_recent_activity(db_session, monkeypatch):
    monkeypatch.setattr(collections_module, "get_search_client", lambda: FixedSearchClient([]))
    monkeypatch.setattr(collections_module, "get_llm_client", lambda: FixedLLMClient([]))

    collection = await collections_module.generate_daily_digest()
    assert collection is None


async def test_generate_daily_digest_returns_none_without_search_results(db_session, monkeypatch):
    await _make_link_with_source(
        db_session, url="https://a.com", priority=5.0, created_days_ago=0, url_hash="h1"
    )
    monkeypatch.setattr(collections_module, "get_search_client", lambda: FixedSearchClient([]))
    monkeypatch.setattr(collections_module, "get_llm_client", lambda: FixedLLMClient([]))

    collection = await collections_module.generate_daily_digest()
    assert collection is None


async def test_generate_daily_digest_creates_collection_with_valid_articles(
    db_session, monkeypatch
):
    await _make_link_with_source(
        db_session, url="https://a.com", priority=5.0, created_days_ago=0, url_hash="h1"
    )

    candidates = [
        SearchResult(title="Found 1", url="https://found1.com", snippet="s1"),
        SearchResult(title="Found 2", url="https://found2.com", snippet="s2"),
    ]
    monkeypatch.setattr(
        collections_module, "get_search_client", lambda: FixedSearchClient(candidates)
    )
    fake_llm = FixedLLMClient(
        [
            DigestArticle(title="Found 1", url="https://found1.com", description="why 1"),
            # анти-галлюцинация: url, которого не было среди кандидатов, отбрасывается
            DigestArticle(title="Made up", url="https://not-a-candidate.com", description="nope"),
        ]
    )
    monkeypatch.setattr(collections_module, "get_llm_client", lambda: fake_llm)

    collection = await collections_module.generate_daily_digest()

    assert collection is not None
    assert collection.theme == collections_module.DAILY_DIGEST_THEME
    assert collection.link_ids == []
    assert len(collection.articles) == 1
    assert collection.articles[0]["url"] == "https://found1.com"
    assert collection.articles[0]["description"] == "why 1"
    assert len(fake_llm.calls) == 1


async def test_generate_daily_digest_excludes_hidden_and_stale_reference_links(
    db_session, monkeypatch
):
    await _make_link_with_source(
        db_session,
        url="https://hidden.com",
        priority=9.0,
        created_days_ago=0,
        url_hash="h-hidden",
        is_hidden=True,
    )
    await _make_link_with_source(
        db_session, url="https://stale.com", priority=9.0, created_days_ago=30, url_hash="h-stale"
    )
    monkeypatch.setattr(
        collections_module,
        "get_search_client",
        lambda: FixedSearchClient([SearchResult(title="X", url="https://x.com", snippet="s")]),
    )
    monkeypatch.setattr(collections_module, "get_llm_client", lambda: FixedLLMClient([]))

    collection = await collections_module.generate_daily_digest()
    assert collection is None  # ни одной ссылки с активностью за последние 24ч


async def test_generate_daily_digest_caps_at_ten_articles(db_session, monkeypatch):
    await _make_link_with_source(
        db_session, url="https://a.com", priority=5.0, created_days_ago=0, url_hash="h1"
    )
    candidates = [
        SearchResult(title=f"F{i}", url=f"https://f{i}.com", snippet="s") for i in range(15)
    ]
    monkeypatch.setattr(
        collections_module, "get_search_client", lambda: FixedSearchClient(candidates)
    )
    articles = [
        DigestArticle(title=f"F{i}", url=f"https://f{i}.com", description="d") for i in range(15)
    ]
    monkeypatch.setattr(collections_module, "get_llm_client", lambda: FixedLLMClient(articles))

    collection = await collections_module.generate_daily_digest()
    assert len(collection.articles) == 10


async def test_generate_weekly_digest_uses_seven_day_window(db_session, monkeypatch):
    # 5 дней назад — не входит в дневное окно (1 день), но входит в недельное (7 дней)
    await _make_link_with_source(
        db_session, url="https://a.com", priority=5.0, created_days_ago=5, url_hash="h1"
    )
    candidates = [SearchResult(title="Found", url="https://found.com", snippet="s")]
    monkeypatch.setattr(
        collections_module, "get_search_client", lambda: FixedSearchClient(candidates)
    )
    monkeypatch.setattr(
        collections_module,
        "get_llm_client",
        lambda: FixedLLMClient(
            [DigestArticle(title="Found", url="https://found.com", description="d")]
        ),
    )

    collection = await collections_module.generate_weekly_digest()
    assert collection is not None
    assert collection.theme == collections_module.WEEKLY_DIGEST_THEME
    assert collection.articles[0]["url"] == "https://found.com"


async def test_generate_weekly_digest_returns_none_for_daily_only_window(db_session, monkeypatch):
    # 5 дней назад не входит в дневное окно — daily должен вернуть None
    await _make_link_with_source(
        db_session, url="https://a.com", priority=5.0, created_days_ago=5, url_hash="h1"
    )
    monkeypatch.setattr(
        collections_module,
        "get_search_client",
        lambda: FixedSearchClient([SearchResult(title="X", url="https://x.com", snippet="s")]),
    )
    monkeypatch.setattr(collections_module, "get_llm_client", lambda: FixedLLMClient([]))

    collection = await collections_module.generate_daily_digest()
    assert collection is None


def test_format_digest_text_lists_articles():
    from db.models import Collection

    collection = Collection(
        title="Daily digest — Jul 12, 2026",
        theme=collections_module.DAILY_DIGEST_THEME,
        summary_md="",
        articles=[
            {"title": "A", "url": "https://a.com", "description": "desc a"},
            {"title": "B", "url": "https://b.com", "description": ""},
        ],
    )
    text = collections_module.format_digest_text(collection)
    assert "1. A — https://a.com" in text
    assert "desc a" in text
    assert "2. B — https://b.com" in text
