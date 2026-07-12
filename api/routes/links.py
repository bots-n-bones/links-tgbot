"""GET /api/links и т.д. (TZ §8) + вспомогательные запросы, переиспользуемые
HTML-страницами дашборда (api/main.py). PATCH-эндпоинты принимают form/query
(не JSON-body) — так проще интегрировать с HTMX без доп. расширений; JSON
PATCH для внешней интеграции (TZ §8) можно добавить позже, когда появится
реальный внешний потребитель (см. TZ §15 — сайт-интеграция вне MVP)."""

from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.posts import get_posts_by_link_ids
from api.templates_env import templates
from db.models import Collection, Link, LinkSource, LinkTag, ManualPriority, Tag
from db.session import get_sessionmaker
from shared.tag_normalizer import normalize_tags
from worker.llm import normalize_area

router = APIRouter(prefix="/api/links", tags=["links"])

PAGE_SIZE = 20
SORT_COLUMNS = {
    "priority": Link.manual_priority.desc(),
    "date": Link.created_at.desc(),
    "tested": Link.is_tested.desc(),
    "usefulness": Link.usefulness_score.desc().nullslast(),
    "count": Link.source_count.desc(),
    "clicks": Link.click_count.desc(),
}

POPULAR_CLICKS_THRESHOLD = (
    3  # порог для бейджа "Популярно" на дашборде (по кликам, не по добавлениям)
)


def _wants_html(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


@dataclass
class LinkListResult:
    items: list[Link]
    total: int
    page: int
    page_size: int


async def query_links(
    session: AsyncSession,
    *,
    tag: str | None = None,
    area: str | None = None,
    chat: str | None = None,
    q: str | None = None,
    source_type: str | None = None,
    sort: str = "date",
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> LinkListResult:
    conditions = [Link.is_hidden.is_(False)]  # F-57: скрытые не в основной ленте

    if tag:
        conditions.append(
            Link.id.in_(
                select(LinkTag.link_id).join(Tag, Tag.id == LinkTag.tag_id).where(Tag.name == tag)
            )
        )
    if area:
        conditions.append(Link.area == area)
    if chat:
        conditions.append(
            Link.id.in_(select(LinkSource.link_id).where(LinkSource.chat_title == chat))
        )
    if source_type:
        conditions.append(
            Link.id.in_(select(LinkSource.link_id).where(LinkSource.source_type == source_type))
        )
    if q:
        like = f"%{q}%"
        conditions.append(
            or_(Link.title.ilike(like), Link.description.ilike(like), Link.url.ilike(like))
        )

    order = SORT_COLUMNS.get(sort, SORT_COLUMNS["date"])
    base_stmt = select(Link).where(*conditions)

    total = (
        await session.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()

    items_stmt = base_stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)
    items = list((await session.execute(items_stmt)).scalars().all())
    for link in items:
        await session.refresh(link, attribute_names=["tags"])

    return LinkListResult(items=items, total=total, page=page, page_size=page_size)


async def get_latest_digest(session: AsyncSession, theme: str) -> Collection | None:
    return await session.scalar(
        select(Collection)
        .where(Collection.theme == theme)
        .order_by(Collection.created_at.desc())
        .limit(1)
    )


async def list_digest_history(
    session: AsyncSession, theme: str, *, offset: int = 0, limit: int = 10
) -> list[Collection]:
    return list(
        (
            await session.execute(
                select(Collection)
                .where(Collection.theme == theme)
                .order_by(Collection.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def list_digest_history_combined(
    session: AsyncSession, themes: list[str], *, offset: int = 0, limit: int = 10
) -> list[Collection]:
    """Daily+weekly дайджесты в одной вкладке (F) — общая лента обеих тем,
    отсортированная по дате, тег Daily/Weekly проставляется в шаблоне по
    collection.theme."""
    return list(
        (
            await session.execute(
                select(Collection)
                .where(Collection.theme.in_(themes))
                .order_by(Collection.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def list_all_tags(session: AsyncSession) -> list[tuple[str, int]]:
    stmt = (
        select(Tag.name, func.count(LinkTag.link_id))
        .join(LinkTag, LinkTag.tag_id == Tag.id)
        .group_by(Tag.name)
        .order_by(Tag.name)
    )
    return list((await session.execute(stmt)).all())


async def get_link_detail(session: AsyncSession, link_id: int) -> Link | None:
    link = await session.get(Link, link_id)
    if link is None:
        return None
    await session.refresh(link, attribute_names=["tags", "sources"])
    return link


class LinkOut(BaseModel):
    id: int
    url: str
    title: str | None
    description: str | None
    area: str | None
    usefulness_score: float | None
    usefulness_breakdown: dict | None
    domain: str | None
    favicon_url: str | None
    status: str
    source_count: int
    unique_senders: int
    priority_score: float
    manual_priority: str
    is_tested: bool
    click_count: int
    is_hidden: bool
    tags: list[str]
    created_at: datetime

    @classmethod
    def from_link(cls, link: Link) -> "LinkOut":
        return cls(
            id=link.id,
            url=link.url,
            title=link.title,
            description=link.description,
            area=link.area,
            usefulness_score=link.usefulness_score,
            usefulness_breakdown=link.usefulness_breakdown,
            domain=link.domain,
            favicon_url=link.favicon_url,
            status=link.status.value,
            source_count=link.source_count,
            unique_senders=link.unique_senders,
            priority_score=link.priority_score,
            manual_priority=link.manual_priority.value,
            is_tested=link.is_tested,
            click_count=link.click_count,
            is_hidden=link.is_hidden,
            tags=[t.name for t in link.tags],
            created_at=link.created_at,
        )


@router.get("")
async def list_links_api(
    tag: str | None = None,
    chat: str | None = None,
    q: str | None = None,
    sort: str = "date",
    page: int = 1,
):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(session, tag=tag, chat=chat, q=q, sort=sort, page=page)
    return {
        "items": [LinkOut.from_link(link).model_dump(mode="json") for link in result.items],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
    }


@router.get("/{link_id}")
async def get_link_api(link_id: int):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        raise HTTPException(404, "Link not found")
    out = LinkOut.from_link(link).model_dump(mode="json")
    out["sources"] = [
        {
            "chat_title": s.chat_title,
            "sender_name": s.sender_name,
            "source_type": s.source_type.value,
            "created_at": s.created_at.isoformat(),
        }
        for s in link.sources
    ]
    return out


@router.patch("/{link_id}")
async def update_link(
    link_id: int,
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    area: str = Form(""),
    priority: str = Form(""),
    tested: bool = Form(False),
    view: str = Form("card"),
):
    """Общая функция редактирования записи: заголовок, описание, теги, area,
    ручной приоритет, отметка "оттестировано" — заменяет старый
    узкоспециализированный PATCH .../tags. view=card|detail определяет, какой
    HTML-фрагмент вернуть (карточка в списке или блок на странице ссылки) —
    сам PATCH и модель данных при этом общие."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            raise HTTPException(404, "Link not found")

        link.title = title.strip() or None
        link.description = description.strip() or None
        if area:
            link.area = normalize_area(area)
        if priority in (p.value for p in ManualPriority):
            link.manual_priority = ManualPriority(priority)
        link.is_tested = tested

        parsed = [t.strip() for t in tags.split(",") if t.strip()]
        normalized = normalize_tags(parsed)

        await session.execute(LinkTag.__table__.delete().where(LinkTag.link_id == link_id))
        for name in normalized:
            existing_tag = await session.scalar(select(Tag).where(Tag.name == name))
            if existing_tag is None:
                existing_tag = Tag(name=name, slug=name)
                session.add(existing_tag)
                await session.flush()
            session.add(LinkTag(link_id=link_id, tag_id=existing_tag.id))
        await session.commit()
        await session.refresh(link, attribute_names=["tags"])

        if _wants_html(request):
            template_name = "_link_detail_view.html" if view == "detail" else "_link_card.html"
            posts_by_link = await get_posts_by_link_ids(session, [link.id])
            return templates.TemplateResponse(
                request, template_name, {"link": link, "posts_by_link": posts_by_link}
            )
        return LinkOut.from_link(link).model_dump(mode="json")


@router.patch("/{link_id}/priority")
async def update_link_priority(link_id: int, request: Request, priority: str = Form(...)):
    """Inline-редактирование Priority прямо в строке таблицы (select с
    hx-trigger=change) — трогает только это поле, в отличие от update_link,
    которому нужна вся форма редактирования целиком."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            raise HTTPException(404, "Link not found")
        if priority not in (p.value for p in ManualPriority):
            raise HTTPException(422, "Invalid priority")
        link.manual_priority = ManualPriority(priority)
        await session.commit()
        await session.refresh(link, attribute_names=["tags"])

        if _wants_html(request):
            posts_by_link = await get_posts_by_link_ids(session, [link.id])
            return templates.TemplateResponse(
                request, "_link_card.html", {"link": link, "posts_by_link": posts_by_link}
            )
        return LinkOut.from_link(link).model_dump(mode="json")


@router.patch("/{link_id}/tested")
async def update_link_tested(link_id: int, request: Request, tested: bool = Form(False)):
    """Inline-редактирование Tested прямо в строке таблицы (чекбокс с
    hx-trigger=change) — снятая галочка не шлёт значение в форме, поэтому
    default=False корректно отражает "unchecked"."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            raise HTTPException(404, "Link not found")
        link.is_tested = tested
        await session.commit()
        await session.refresh(link, attribute_names=["tags"])

        if _wants_html(request):
            posts_by_link = await get_posts_by_link_ids(session, [link.id])
            return templates.TemplateResponse(
                request, "_link_card.html", {"link": link, "posts_by_link": posts_by_link}
            )
        return LinkOut.from_link(link).model_dump(mode="json")


@router.patch("/{link_id}/hide")
async def update_hide(link_id: int, request: Request, hidden: bool = Query(True)):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            raise HTTPException(404, "Link not found")
        link.is_hidden = hidden
        await session.commit()

        if hidden:
            if _wants_html(request):
                return HTMLResponse("")  # HTMX: убираем карточку из ленты
            return {"id": link_id, "is_hidden": True}

        await session.refresh(link, attribute_names=["tags"])
        if _wants_html(request):
            return templates.TemplateResponse(request, "_link_card.html", {"link": link})
        return {"id": link_id, "is_hidden": False}
