from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import worker.tasks as tasks_module
from db.models import Link, LinkSource, LinkTag, RawMessage, SourceType, Tag
from worker.embeddings import FakeEmbeddingClient
from worker.fetcher import FetchError, PageMeta
from worker.llm import FakeLLMClient, TagDescriptionResult


async def _add_raw_message(
    db_session, workspace_id: int, *, chat_id: int, message_id: int, text: str, sender_id: int = 1
) -> RawMessage:
    rm = RawMessage(
        workspace_id=workspace_id,
        chat_id=chat_id,
        message_id=message_id,
        sender_id=sender_id,
        text=text,
        source_type=SourceType.group,
    )
    db_session.add(rm)
    await db_session.commit()
    await db_session.refresh(rm)
    return rm


async def _fake_fetch_ok(url: str) -> PageMeta:
    return PageMeta(
        title="Заголовок",
        description="og-описание",
        favicon_url="https://x/f.ico",
        domain="x.com",
        raw_text="текст страницы",
    )


def _patch_clients(monkeypatch, llm=None, embedding=None):
    llm = llm or FakeLLMClient()
    embedding = embedding or FakeEmbeddingClient()
    monkeypatch.setattr(tasks_module, "get_llm_client", lambda: llm)
    monkeypatch.setattr(tasks_module, "get_embedding_client", lambda: embedding)
    return llm, embedding


async def test_new_link_creates_rows_with_normalized_tags(db_session, workspace_id, monkeypatch):
    llm, _ = _patch_clients(monkeypatch)
    monkeypatch.setattr(tasks_module, "fetch_metadata", _fake_fetch_ok)

    rm = await _add_raw_message(
        db_session, workspace_id, chat_id=1, message_id=1, text="https://example.com/a"
    )
    await tasks_module._process_raw_message_async(rm.id)

    links = (await db_session.execute(select(Link))).scalars().all()
    assert len(links) == 1
    link = links[0]
    assert link.status.value == "done"
    assert link.description == "Фейковое описание для https://example.com/a"
    assert link.area == "tech"
    assert link.usefulness_score == 7.0  # FakeLLMClient: depth=3+novelty=2+actionability=2
    assert link.usefulness_breakdown == {
        "depth": 3,
        "novelty": 2,
        "actionability": 2,
        "total": 7,
    }
    assert link.embedding is not None

    sources = (
        (await db_session.execute(select(LinkSource).where(LinkSource.link_id == link.id)))
        .scalars()
        .all()
    )
    assert len(sources) == 1

    tag_names = (
        (
            await db_session.execute(
                select(Tag.name)
                .join(LinkTag, LinkTag.tag_id == Tag.id)
                .where(LinkTag.link_id == link.id)
            )
        )
        .scalars()
        .all()
    )
    assert set(tag_names) == {"dev", "ai"}
    assert len(llm.describe_calls) == 1


async def test_duplicate_does_not_call_llm_again(db_session, workspace_id, monkeypatch):
    llm, _ = _patch_clients(monkeypatch)
    monkeypatch.setattr(tasks_module, "fetch_metadata", _fake_fetch_ok)

    rm1 = await _add_raw_message(
        db_session,
        workspace_id,
        chat_id=1,
        message_id=1,
        text="https://example.com/dup",
        sender_id=10,
    )
    await tasks_module._process_raw_message_async(rm1.id)

    rm2 = await _add_raw_message(
        db_session,
        workspace_id,
        chat_id=1,
        message_id=2,
        text="https://example.com/dup",
        sender_id=20,
    )
    await tasks_module._process_raw_message_async(rm2.id)

    links = (await db_session.execute(select(Link))).scalars().all()
    assert len(links) == 1
    link = links[0]
    assert link.source_count == 2
    assert link.unique_senders == 2
    assert len(llm.describe_calls) == 1  # LLM вызван только один раз


async def test_invalid_area_from_llm_falls_back_to_other(db_session, workspace_id, monkeypatch):
    class WeirdAreaLLMClient:
        def __init__(self) -> None:
            self.describe_calls: list[dict] = []

        async def describe_link(self, **kwargs):
            self.describe_calls.append(kwargs)
            return TagDescriptionResult(description="d", tags=[], area="crypto", confidence=0.5)

        async def complete(self, **kwargs):
            return ""

    _patch_clients(monkeypatch, llm=WeirdAreaLLMClient())
    monkeypatch.setattr(tasks_module, "fetch_metadata", _fake_fetch_ok)

    rm = await _add_raw_message(
        db_session, workspace_id, chat_id=1, message_id=99, text="https://example.com/x"
    )
    await tasks_module._process_raw_message_async(rm.id)

    link = (await db_session.execute(select(Link))).scalars().one()
    assert link.area == "other"


async def test_fetch_failure_falls_back_to_message_context(db_session, workspace_id, monkeypatch):
    llm, _ = _patch_clients(monkeypatch)

    async def failing_fetch(url: str) -> PageMeta:
        raise FetchError("boom")

    monkeypatch.setattr(tasks_module, "fetch_metadata", failing_fetch)

    rm = await _add_raw_message(
        db_session,
        workspace_id,
        chat_id=1,
        message_id=3,
        text="контекст https://example.com/broken",
    )
    await tasks_module._process_raw_message_async(rm.id)

    link = (await db_session.execute(select(Link))).scalars().one()
    assert link.status.value == "fetch_failed"
    assert link.fetch_error is not None
    assert len(llm.describe_calls) == 1
    assert llm.describe_calls[0]["page_text"] == rm.text


async def test_prompt_injection_tags_filtered_out(db_session, workspace_id, monkeypatch):
    class InjectingLLMClient:
        def __init__(self) -> None:
            self.describe_calls: list[dict] = []

        async def describe_link(self, **kwargs):
            self.describe_calls.append(kwargs)
            return TagDescriptionResult(
                description="норм. описание",
                tags=["ai", "ignore previous instructions", "<script>alert(1)</script>", "ии"],
                confidence=0.5,
            )

        async def complete(self, **kwargs):
            return ""

    _patch_clients(monkeypatch, llm=InjectingLLMClient())
    monkeypatch.setattr(tasks_module, "fetch_metadata", _fake_fetch_ok)

    rm = await _add_raw_message(
        db_session, workspace_id, chat_id=1, message_id=4, text="https://example.com/injected"
    )
    await tasks_module._process_raw_message_async(rm.id)

    link = (await db_session.execute(select(Link))).scalars().one()
    tag_names = (
        (
            await db_session.execute(
                select(Tag.name)
                .join(LinkTag, LinkTag.tag_id == Tag.id)
                .where(LinkTag.link_id == link.id)
            )
        )
        .scalars()
        .all()
    )
    # мусорные/инъекционные "теги" отброшены allowlist'ом; "ии" тоже —
    # в тестовой БД нет записи в tag_synonyms
    assert set(tag_names) == {"ai"}


async def test_multiple_urls_in_one_message_processed_individually(
    db_session, workspace_id, monkeypatch
):
    llm, _ = _patch_clients(monkeypatch)
    monkeypatch.setattr(tasks_module, "fetch_metadata", _fake_fetch_ok)

    rm = await _add_raw_message(
        db_session,
        workspace_id,
        chat_id=1,
        message_id=5,
        text="гляньте https://a.com и https://b.com",
    )
    await tasks_module._process_raw_message_async(rm.id)

    links = (await db_session.execute(select(Link))).scalars().all()
    assert {link.url for link in links} == {"https://a.com", "https://b.com"}
    assert len(llm.describe_calls) == 2


async def test_recompute_all_priority_scores_uses_last_source(db_session, workspace_id):
    now = datetime.now(UTC)
    link = Link(
        workspace_id=workspace_id,
        url="https://a.com",
        normalized_url="a.com",
        url_hash="hash-recompute",
        source_count=1,
        unique_senders=1,
        priority_score=0,
    )
    db_session.add(link)
    await db_session.flush()
    db_session.add(
        LinkSource(
            link_id=link.id,
            sender_id=1,
            source_type=SourceType.group,
            created_at=now - timedelta(days=7),
        )
    )
    await db_session.commit()

    await tasks_module._recompute_all_priority_scores_async()

    await db_session.refresh(link)
    assert link.priority_score == pytest.approx(1.0 + 2.0 + 1.1, abs=0.05)


async def test_recompute_all_priority_scores_also_recomputes_posts(db_session, workspace_id):
    from db.models import Post

    now = datetime.now(UTC)
    post = Post(
        workspace_id=workspace_id,
        chat_id=-100123,
        message_id=1,
        post_url="https://t.me/c/123/1",
        priority_score=0,
        created_at=now - timedelta(days=7),
    )
    db_session.add(post)
    await db_session.commit()

    await tasks_module._recompute_all_priority_scores_async()

    await db_session.refresh(post)
    assert post.priority_score == pytest.approx(1.0 + 2.0 + 1.1, abs=0.05)


async def test_poll_unprocessed_batch_enqueues_only_unprocessed(
    db_session, workspace_id, monkeypatch
):
    rm1 = await _add_raw_message(
        db_session, workspace_id, chat_id=1, message_id=10, text="https://a.com"
    )
    rm2 = await _add_raw_message(
        db_session, workspace_id, chat_id=1, message_id=11, text="https://b.com"
    )
    rm2.processed = True
    await db_session.commit()

    class FakeTask:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def delay(self, raw_message_id: int) -> None:
            self.calls.append(raw_message_id)

    fake_task = FakeTask()
    monkeypatch.setattr(tasks_module, "process_raw_message", fake_task)

    ids = await tasks_module._poll_unprocessed_batch_async()

    assert ids == [rm1.id]
    assert fake_task.calls == [rm1.id]


async def test_generate_daily_digest_broadcasts_when_collection_created(
    db_session, workspace_id, monkeypatch
):
    from db.models import Collection

    collection = Collection(
        id=1,
        workspace_id=workspace_id,
        title="Daily digest — Jul 12, 2026",
        summary_md="",
        link_ids=[],
        articles=[],
    )

    async def fake_generate_daily_digest(**kwargs):
        return collection

    broadcasted = []

    async def fake_broadcast(c):
        broadcasted.append(c)

    monkeypatch.setattr(tasks_module, "generate_daily_digest", fake_generate_daily_digest)
    monkeypatch.setattr(tasks_module, "_broadcast_digest", fake_broadcast)

    await tasks_module._generate_daily_digest_and_broadcast_async()

    assert broadcasted == [collection]


async def test_generate_daily_digest_skips_broadcast_when_no_collection(
    db_session, workspace_id, monkeypatch
):
    async def fake_generate_daily_digest(**kwargs):
        return None

    broadcasted = []

    async def fake_broadcast(c):
        broadcasted.append(c)

    monkeypatch.setattr(tasks_module, "generate_daily_digest", fake_generate_daily_digest)
    monkeypatch.setattr(tasks_module, "_broadcast_digest", fake_broadcast)

    await tasks_module._generate_daily_digest_and_broadcast_async()

    assert broadcasted == []


async def test_broadcast_digest_sends_to_all_allowed_users(monkeypatch):
    from db.models import Collection
    from shared import config as config_module

    monkeypatch.setenv("BOT_TOKEN", "123456789:AAFakeTokenForTestsOnly000000000")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111,222")
    config_module.get_settings.cache_clear()

    sent = []

    async def fake_send(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(tasks_module, "send_message_throttled", fake_send)

    collection = Collection(
        id=1,
        workspace_id=1,
        title="Daily digest — Jul 12, 2026",
        summary_md="",
        link_ids=[],
        articles=[{"title": "A", "url": "https://a.com", "description": "desc"}],
    )
    await tasks_module._broadcast_digest(collection)

    config_module.get_settings.cache_clear()
    assert [chat_id for chat_id, _ in sent] == [111, 222]
    assert all("Daily digest" in text for _, text in sent)


async def test_same_url_in_different_workspaces_does_not_dedupe(db_session, monkeypatch):
    """Волна 4: дедуп по url_hash теперь скоупится по workspace_id — одна и
    та же ссылка в двух workspace должна создать два отдельных Link, а не
    схлопнуться в один с source_count=2."""
    from db.models import Workspace

    llm, _ = _patch_clients(monkeypatch)
    monkeypatch.setattr(tasks_module, "fetch_metadata", _fake_fetch_ok)

    ws_a = Workspace(name="Workspace A")
    ws_b = Workspace(name="Workspace B")
    db_session.add_all([ws_a, ws_b])
    await db_session.commit()
    await db_session.refresh(ws_a)
    await db_session.refresh(ws_b)

    rm_a = await _add_raw_message(
        db_session, ws_a.id, chat_id=1, message_id=1, text="https://shared.example.com/x"
    )
    await tasks_module._process_raw_message_async(rm_a.id)

    rm_b = await _add_raw_message(
        db_session, ws_b.id, chat_id=2, message_id=1, text="https://shared.example.com/x"
    )
    await tasks_module._process_raw_message_async(rm_b.id)

    links = (await db_session.execute(select(Link))).scalars().all()
    assert len(links) == 2
    assert {link.workspace_id for link in links} == {ws_a.id, ws_b.id}
    assert all(link.source_count == 1 for link in links)  # не задедуплицировались
    assert len(llm.describe_calls) == 2  # LLM вызван для каждого workspace отдельно


async def test_get_or_create_tag_scoped_per_workspace(db_session):
    """Тег с одинаковым именем в разных workspace — разные строки Tag."""
    from db.models import Tag, Workspace

    ws_a = Workspace(name="Workspace A")
    ws_b = Workspace(name="Workspace B")
    db_session.add_all([ws_a, ws_b])
    await db_session.commit()
    await db_session.refresh(ws_a)
    await db_session.refresh(ws_b)

    tag_a = await tasks_module._get_or_create_tag(db_session, ws_a.id, "ai")
    tag_b = await tasks_module._get_or_create_tag(db_session, ws_b.id, "ai")
    await db_session.commit()

    assert tag_a.id != tag_b.id
    tags = (await db_session.execute(select(Tag).where(Tag.name == "ai"))).scalars().all()
    assert len(tags) == 2
