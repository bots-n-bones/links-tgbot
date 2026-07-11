"""Обработка постов из групповых чатов (F: вкладка Posts) — сохраняем каждое
сообщение (со ссылками или без), классифицируем через LLM (summary/tags/area).
Ссылки внутри поста по-прежнему идут по обычному link-пайплайну отдельно —
здесь только пытаемся сослаться на уже созданные Link по url_hash."""

from pathlib import Path

from aiogram import Bot
from sqlalchemy import select

from db.models import Link, Post, PostTag, Tag
from db.session import get_sessionmaker
from shared.config import get_settings
from shared.tag_normalizer import normalize_tags
from shared.url_normalizer import normalize_url, url_hash
from worker.llm import get_llm_client, normalize_area

PHOTO_DIR = Path("api/static/posts")


async def _download_post_photo(file_id: str) -> str | None:
    settings = get_settings()
    if not settings.bot_token:
        return None
    bot = Bot(token=settings.bot_token)
    try:
        file = await bot.get_file(file_id)
        if not file.file_path:
            return None
        PHOTO_DIR.mkdir(parents=True, exist_ok=True)
        dest = PHOTO_DIR / f"{file_id}.jpg"
        await bot.download_file(file.file_path, destination=dest)
        return f"/static/posts/{dest.name}"
    finally:
        await bot.session.close()


async def process_post(payload: dict) -> int | None:
    settings = get_settings()
    llm_client = get_llm_client()
    sessionmaker = get_sessionmaker()

    text = (payload.get("text") or "").strip()

    async with sessionmaker() as session:
        existing = await session.scalar(
            select(Post).where(
                Post.chat_id == payload["chat_id"], Post.message_id == payload["message_id"]
            )
        )
        if existing is not None:
            return existing.id

        classification = await llm_client.classify_post(
            text=text or "(no text)", model=settings.openai_model_mini
        )
        area = normalize_area(classification.area)
        tag_names = normalize_tags(classification.tags)

        photo_url = None
        photo_file_id = payload.get("photo_file_id")
        if photo_file_id:
            photo_url = await _download_post_photo(photo_file_id)

        link_ids: list[int] = []
        for url in payload.get("urls", []):
            h = url_hash(normalize_url(url))
            link = await session.scalar(select(Link).where(Link.url_hash == h))
            if link is not None:
                link_ids.append(link.id)

        post = Post(
            chat_id=payload["chat_id"],
            message_id=payload["message_id"],
            chat_title=payload.get("chat_title"),
            sender_id=payload.get("sender_id"),
            sender_name=payload.get("sender_name"),
            text=text or None,
            post_url=payload.get("post_url"),
            summary=classification.summary,
            area=area,
            photo_url=photo_url,
            link_ids=link_ids,
        )
        session.add(post)
        await session.flush()

        for name in tag_names:
            tag = await session.scalar(select(Tag).where(Tag.name == name))
            if tag is None:
                tag = Tag(name=name, slug=name)
                session.add(tag)
                await session.flush()
            session.add(PostTag(post_id=post.id, tag_id=tag.id))

        await session.commit()
        await session.refresh(post)
        return post.id
