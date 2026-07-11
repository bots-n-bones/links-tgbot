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

from api.templates_env import templates
from db.models import Collection, Link, LinkSource, LinkTag, Tag
from db.session import get_sessionmaker
from shared.tag_normalizer import normalize_tags
from worker.collections import DAILY_TOP3_THEME

router = APIRouter(prefix="/api/links", tags=["links"])

PAGE_SIZE = 20
SORT_COLUMNS = {
    "priority": Link.priority_score.desc(),
    "date": Link.created_at.desc(),
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
    chat: str | None = None,
    q: str | None = None,
    source_type: str | None = None,
    sort: str = "priority",
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

    order = SORT_COLUMNS.get(sort, SORT_COLUMNS["priority"])
    base_stmt = select(Link).where(*conditions)

    total = (
        await session.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()

    items_stmt = base_stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)
    items = list((await session.execute(items_stmt)).scalars().all())
    for link in items:
        await session.refresh(link, attribute_names=["tags"])

    return LinkListResult(items=items, total=total, page=page, page_size=page_size)


async def get_latest_daily_top3(session: AsyncSession) -> tuple[Collection | None, list[Link]]:
    """Последняя ежедневная подборка топ-3 (Celery Beat, 12:00) — заменяет
    старый блок «Сейчас в топе у команды»."""
    collection = await session.scalar(
        select(Collection)
        .where(Collection.theme == DAILY_TOP3_THEME)
        .order_by(Collection.created_at.desc())
        .limit(1)
    )
    if collection is None or not collection.link_ids:
        return None, []

    links = list(
        (
            await session.execute(
                select(Link).where(Link.id.in_(collection.link_ids), Link.is_hidden.is_(False))
            )
        )
        .scalars()
        .all()
    )
    order = {link_id: i for i, link_id in enumerate(collection.link_ids)}
    links.sort(key=lambda link: order.get(link.id, len(order)))
    for link in links:
        await session.refresh(link, attribute_names=["tags"])
    return collection, links


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
    domain: str | None
    favicon_url: str | None
    status: str
    source_count: int
    unique_senders: int
    priority_score: float
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
            domain=link.domain,
            favicon_url=link.favicon_url,
            status=link.status.value,
            source_count=link.source_count,
            unique_senders=link.unique_senders,
            priority_score=link.priority_score,
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
    sort: str = "priority",
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
    view: str = Form("card"),
):
    """Общая функция редактирования записи: заголовок, описание, теги —
    заменяет старый узкоспециализированный PATCH .../tags. view=card|detail
    определяет, какой HTML-фрагмент вернуть (карточка в списке или блок на
    странице ссылки) — сам PATCH и модель данных при этом общие."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            raise HTTPException(404, "Link not found")

        link.title = title.strip() or None
        link.description = description.strip() or None

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
            return templates.TemplateResponse(request, template_name, {"link": link})
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
