"""Обработка постов из групповых чатов (F: вкладка Posts) — сохраняем каждое
сообщение (со ссылками или без), классифицируем через LLM (summary/tags/area).
Ссылки внутри поста по-прежнему идут по обычному link-пайплайну отдельно —
здесь только пытаемся сослаться на уже созданные Link по url_hash."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from aiogram import Bot
from sqlalchemy import select

from db.models import Link, Post, PostTag, Tag
from db.session import get_sessionmaker
from shared.config import get_settings
from shared.tag_normalizer import normalize_tags
from shared.telegram_throttle import send_message_throttled
from shared.url_normalizer import normalize_url, url_hash
from worker.embeddings import get_embedding_client
from worker.llm import get_llm_client, normalize_area
from worker.priority import compute_priority_score

logger = logging.getLogger(__name__)

PHOTO_DIR = Path("api/static/posts")


@dataclass
class PostResult:
    post_id: int
    is_new: bool
    area: str | None
    tags: list[str]
    link_count: int
    post_url: str | None = None
    link_summaries: list[str] = field(default_factory=list)


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


async def _process_post_inner(payload: dict) -> PostResult:
    settings = get_settings()
    llm_client = get_llm_client()
    embedding_client = get_embedding_client()
    sessionmaker = get_sessionmaker()

    text = (payload.get("text") or "").strip()
    workspace_id = payload["workspace_id"]

    async with sessionmaker() as session:
        existing = await session.scalar(
            select(Post).where(
                Post.workspace_id == workspace_id,
                Post.chat_id == payload["chat_id"],
                Post.message_id == payload["message_id"],
            )
        )
        if existing is not None:
            await session.refresh(existing, attribute_names=["tags"])
            return PostResult(
                post_id=existing.id,
                is_new=False,
                area=existing.area,
                tags=[t.name for t in existing.tags],
                link_count=len(existing.link_ids or []),
                post_url=existing.post_url,
            )

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
        link_summaries: list[str] = []
        for url in payload.get("urls", []):
            h = url_hash(normalize_url(url))
            link = await session.scalar(
                select(Link).where(Link.workspace_id == workspace_id, Link.url_hash == h)
            )
            if link is not None:
                link_ids.append(link.id)
                await session.refresh(link, attribute_names=["tags"])
                tags_text = ", ".join(t.name for t in link.tags) or "—"
                link_summaries.append(f"{link.url} (теги: {tags_text})")

        embedding = await embedding_client.embed(f"{text} {classification.summary}".strip())

        now = datetime.now(UTC)
        post = Post(
            workspace_id=workspace_id,
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
            embedding=embedding,
            priority_score=compute_priority_score(1, 1, now, now),
        )
        session.add(post)
        await session.flush()

        for name in tag_names:
            tag = await session.scalar(
                select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == name)
            )
            if tag is None:
                tag = Tag(workspace_id=workspace_id, name=name, slug=name)
                session.add(tag)
                await session.flush()
            session.add(PostTag(post_id=post.id, tag_id=tag.id))

        await session.commit()
        await session.refresh(post)
        return PostResult(
            post_id=post.id,
            is_new=True,
            area=area,
            tags=tag_names,
            link_count=len(link_ids),
            post_url=post.post_url,
            link_summaries=link_summaries,
        )


async def _notify(chat_id: int, text: str) -> None:
    settings = get_settings()
    if not settings.bot_token:
        return
    bot = Bot(token=settings.bot_token)
    try:
        await send_message_throttled(bot, chat_id, text)
    finally:
        await bot.session.close()


def _success_text(result: PostResult) -> str:
    if not result.is_new:
        return f"✓ Уже в базе: {result.post_url}"
    tags_text = ", ".join(result.tags) if result.tags else "—"
    lines = [f"✓ Добавлено: {result.post_url}", f"Теги: {tags_text}"]
    if result.link_summaries:
        lines.append("Ссылки внутри поста:")
        lines.extend(f"- {s}" for s in result.link_summaries)
    return "\n".join(lines)


async def process_post(payload: dict) -> int | None:
    notify = bool(payload.get("notify"))
    chat_id = payload.get("chat_id")

    try:
        result = await _process_post_inner(payload)
    except Exception:
        logger.exception(
            "Не удалось обработать пост chat_id=%s message_id=%s",
            payload.get("chat_id"),
            payload.get("message_id"),
        )
        if notify and chat_id:
            await _notify(chat_id, "Не смог добавить пост из-за ошибки. Попробуйте ещё раз позже.")
        raise

    if notify and chat_id:
        await _notify(chat_id, _success_text(result))

    return result.post_id
