"""Вспомогательные запросы для страницы /posts (F: вкладка Posts) + PATCH
/api/posts/{id}/hide (аналог /api/links/{id}/hide)."""

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_workspace_id
from db.models import Post, PostTag, Tag
from db.session import get_sessionmaker

router = APIRouter(prefix="/api/posts", tags=["posts"])

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
    workspace_id: int,
    tag: str | None = None,
    area: str | None = None,
    sort: str = "priority",
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> PostListResult:
    conditions = [Post.workspace_id == workspace_id, Post.is_hidden.is_(False)]
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


async def list_all_post_tags(session: AsyncSession, workspace_id: int) -> list[tuple[str, int]]:
    stmt = (
        select(Tag.name, func.count(PostTag.post_id))
        .join(PostTag, PostTag.tag_id == Tag.id)
        .where(Tag.workspace_id == workspace_id)
        .group_by(Tag.name)
        .order_by(Tag.name)
    )
    return list((await session.execute(stmt)).all())


async def get_posts_by_link_ids(
    session: AsyncSession, workspace_id: int, link_ids: list[int]
) -> dict[int, Post]:
    """Обратный поиск: для каждой ссылки — пост, из которого она пришла (если
    пришла из поста). Пробегает все посты со ссылками — ок для текущих
    объёмов, не оптимизировано под масштаб."""
    if not link_ids:
        return {}
    wanted = set(link_ids)
    rows = (
        (
            await session.execute(
                select(Post).where(Post.workspace_id == workspace_id, Post.link_ids.isnot(None))
            )
        )
        .scalars()
        .all()
    )
    result: dict[int, Post] = {}
    for post in rows:
        for lid in post.link_ids or []:
            if lid in wanted:
                result[lid] = post
    return result


@router.patch("/{post_id}/hide")
async def hide_post(
    post_id: int,
    request: Request,
    hidden: bool = Query(True),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    if workspace_id is None:
        raise HTTPException(401, "Not logged in")
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        post = await session.get(Post, post_id)
        if post is None or post.workspace_id != workspace_id:
            raise HTTPException(404, "Post not found")
        post.is_hidden = hidden
        await session.commit()

    if request.headers.get("hx-request") == "true":
        return HTMLResponse("")  # HTMX: убираем строку из таблицы
    return {"id": post_id, "is_hidden": hidden}
