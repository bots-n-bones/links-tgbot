"""Вспомогательные запросы для страницы /posts (F: вкладка Posts)."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Post, PostTag, Tag

PAGE_SIZE = 20
SORT_COLUMNS = {
    "priority": Post.priority_score.desc(),
    "date": Post.created_at.desc(),
}


@dataclass
class PostListResult:
    items: list[Post]
    total: int
    page: int
    page_size: int


async def query_posts(
    session: AsyncSession,
    *,
    tag: str | None = None,
    area: str | None = None,
    sort: str = "priority",
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> PostListResult:
    conditions = []
    if tag:
        conditions.append(
            Post.id.in_(
                select(PostTag.post_id).join(Tag, Tag.id == PostTag.tag_id).where(Tag.name == tag)
            )
        )
    if area:
        conditions.append(Post.area == area)

    order = SORT_COLUMNS.get(sort, SORT_COLUMNS["priority"])
    base_stmt = select(Post).where(*conditions)
    total = (
        await session.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()

    items_stmt = base_stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)
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


async def get_posts_by_link_ids(session: AsyncSession, link_ids: list[int]) -> dict[int, Post]:
    """Обратный поиск: для каждой ссылки — пост, из которого она пришла (если
    пришла из поста). Пробегает все посты со ссылками — ок для текущих
    объёмов, не оптимизировано под масштаб."""
    if not link_ids:
        return {}
    wanted = set(link_ids)
    rows = (
        (await session.execute(select(Post).where(Post.link_ids.isnot(None))))
        .scalars()
        .all()
    )
    result: dict[int, Post] = {}
    for post in rows:
        for lid in post.link_ids or []:
            if lid in wanted:
                result[lid] = post
    return result
