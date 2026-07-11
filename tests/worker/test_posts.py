import hashlib

from sqlalchemy import select

from db.models import Link, LinkStatus, Post
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
