import hashlib

import pytest
from sqlalchemy import select

import worker.posts as posts_module
from db.models import Link, LinkStatus, Post
from shared import config as config_module
from worker.posts import process_post


async def test_process_post_creates_row_with_classification(db_session):
    post_id = await process_post(
        {
            "chat_id": -100123,
            "message_id": 1,
            "chat_title": "Team chat",
            "sender_id": 5,
            "sender_name": "Alice",
            "text": "Check this out",
            "urls": [],
            "post_url": "https://t.me/c/123/1",
        }
    )

    post = await db_session.get(Post, post_id)
    assert post is not None
    assert post.chat_title == "Team chat"
    assert post.area == "tech"  # FakeLLMClient.classify_post
    assert "Фейковое резюме поста" in post.summary
    assert post.link_ids == []
    await db_session.refresh(post, attribute_names=["tags"])
    assert {t.name for t in post.tags} == {"dev"}


async def test_process_post_is_idempotent_per_chat_and_message(db_session):
    payload = {
        "chat_id": -100123,
        "message_id": 2,
        "chat_title": "Team chat",
        "sender_id": 5,
        "sender_name": "Alice",
        "text": "hello",
        "urls": [],
        "post_url": "https://t.me/c/123/2",
    }
    id_1 = await process_post(payload)
    id_2 = await process_post(payload)
    assert id_1 == id_2

    rows = (await db_session.execute(select(Post).where(Post.message_id == 2))).scalars().all()
    assert len(rows) == 1


async def test_process_post_links_to_existing_link_by_url(db_session):
    link = Link(
        url="https://example.com/a",
        normalized_url="https://example.com/a",
        url_hash=hashlib.sha256(b"https://example.com/a").hexdigest(),
        title="A",
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)

    post_id = await process_post(
        {
            "chat_id": -100123,
            "message_id": 3,
            "chat_title": "Team chat",
            "sender_id": 5,
            "sender_name": "Alice",
            "text": "check https://example.com/a",
            "urls": ["https://example.com/a"],
            "post_url": "https://t.me/c/123/3",
        }
    )

    post = await db_session.get(Post, post_id)
    assert post.link_ids == [link.id]


async def test_process_post_without_text_still_gets_summary(db_session):
    post_id = await process_post(
        {
            "chat_id": -100123,
            "message_id": 4,
            "chat_title": "Team chat",
            "sender_id": 5,
            "sender_name": "Alice",
            "text": None,
            "urls": [],
            "post_url": "https://t.me/c/123/4",
        }
    )
    post = await db_session.get(Post, post_id)
    assert post.summary  # не пусто, даже без текста


async def test_process_post_computes_embedding(db_session):
    post_id = await process_post(
        {
            "chat_id": -100123,
            "message_id": 50,
            "chat_title": "Team chat",
            "sender_id": 5,
            "sender_name": "Alice",
            "text": "hello",
            "urls": [],
            "post_url": "https://t.me/c/123/50",
        }
    )
    post = await db_session.get(Post, post_id)
    assert post.embedding is not None
    assert len(post.embedding) == 1536


async def test_process_post_sets_priority_score(db_session):
    post_id = await process_post(
        {
            "chat_id": -100123,
            "message_id": 5,
            "chat_title": "Team chat",
            "sender_id": 5,
            "sender_name": "Alice",
            "text": "hello",
            "urls": [],
            "post_url": "https://t.me/c/123/5",
        }
    )
    post = await db_session.get(Post, post_id)
    assert post.priority_score > 0


@pytest.fixture
def _bot_token(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123456789:AAFakeTokenForTestsOnly000000000")
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


async def test_process_post_notifies_on_success_when_new(db_session, _bot_token, monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(posts_module, "send_message_throttled", fake_send)

    await process_post(
        {
            "chat_id": 42,
            "message_id": 6,
            "chat_title": "DM",
            "sender_id": 5,
            "sender_name": "Alice",
            "text": "hello",
            "urls": [],
            "post_url": "https://t.me/c/1/6",
            "notify": True,
        }
    )

    assert len(sent) == 1
    chat_id, text = sent[0]
    assert chat_id == 42
    assert "✓ Добавлено" in text


async def test_process_post_notify_includes_resolved_link_summaries(
    db_session, _bot_token, monkeypatch
):
    link = Link(
        url="https://example.com/a",
        normalized_url="https://example.com/a",
        url_hash=hashlib.sha256(b"https://example.com/a").hexdigest(),
        title="A",
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.commit()

    sent = []

    async def fake_send(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(posts_module, "send_message_throttled", fake_send)

    await process_post(
        {
            "chat_id": 42,
            "message_id": 10,
            "chat_title": "DM",
            "sender_id": 5,
            "sender_name": "Alice",
            "text": "check https://example.com/a",
            "urls": ["https://example.com/a"],
            "post_url": "https://t.me/c/1/10",
            "notify": True,
        }
    )

    assert len(sent) == 1
    text = sent[0][1]
    assert "✓ Добавлено" in text
    assert "https://example.com/a" in text


async def test_process_post_notifies_already_saved_on_duplicate(db_session, _bot_token, monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(posts_module, "send_message_throttled", fake_send)

    payload = {
        "chat_id": 42,
        "message_id": 7,
        "chat_title": "DM",
        "sender_id": 5,
        "sender_name": "Alice",
        "text": "hello",
        "urls": [],
        "post_url": "https://t.me/c/1/7",
        "notify": True,
    }
    await process_post(payload)
    sent.clear()
    await process_post(payload)

    assert len(sent) == 1
    assert "✓ Уже в базе" in sent[0][1]


async def test_process_post_notifies_on_error_and_reraises(db_session, _bot_token, monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(posts_module, "send_message_throttled", fake_send)

    async def broken_inner(payload):
        raise RuntimeError("boom")

    monkeypatch.setattr(posts_module, "_process_post_inner", broken_inner)

    with pytest.raises(RuntimeError):
        await process_post(
            {
                "chat_id": 42,
                "message_id": 8,
                "notify": True,
            }
        )

    assert len(sent) == 1
    assert "ошибк" in sent[0][1].lower()


async def test_process_post_does_not_notify_without_notify_flag(db_session, _bot_token, monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(posts_module, "send_message_throttled", fake_send)

    await process_post(
        {
            "chat_id": -100123,
            "message_id": 9,
            "chat_title": "Team chat",
            "sender_id": 5,
            "sender_name": "Alice",
            "text": "hello",
            "urls": [],
            "post_url": "https://t.me/c/123/9",
        }
    )

    assert sent == []
