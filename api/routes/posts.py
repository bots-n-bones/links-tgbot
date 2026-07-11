"""Вспомогательные запросы для страницы /posts (F: вкладка Posts)."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Post, PostTag, Tag

PAGE_SIZE = 20


@dataclass
class PostListResult:
    items: list[Post]
    total: int
    page: int
    page_size: int


async def query_posts(
    session: AsyncSession,
    *,
    area: str | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> PostListResult:
    conditions = []
    if area:
        conditions.append(Post.area == area)

    base_stmt = select(Post).where(*conditions)
    total = (
        await session.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()

    items_stmt = (
        base_stmt.order_by(Post.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = list((await session.execute(items_stmt)).scalars().all())
    for post in items:
        await session.refresh(post, attribute_names=["tags"])

    return PostListResult(items=items, total=total, page=page, page_size=page_size)


async def list_all_post_tags(session: AsyncSession) -> list[tuple[str, int]]:
    stmt = (
        select(Tag.name, func.count(PostTag.post_id))
        .join(PostTag, PostTag.tag_id == Tag.id)
        .group_by(Tag.name)
        .order_by(Tag.name)
    )
    return list((await session.execute(stmt)).all())
