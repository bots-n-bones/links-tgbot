"""GET /api/links и т.д. (TZ §8) + вспомогательные запросы, переиспользуемые
HTML-страницами дашборда (api/main.py). PATCH-эндпоинты принимают form/query
(не JSON-body) — так проще интегрировать с HTMX без доп. расширений; JSON
PATCH для внешней интеграции (TZ §8) можно добавить позже, когда появится
реальный внешний потребитель (см. TZ §15 — сайт-интеграция вне MVP)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.deps import get_current_user, get_current_workspace_id
from api.routes.posts import get_posts_by_link_ids
from api.templates_env import templates
from db.models import (
    CatalogView,
    Collection,
    Link,
    LinkSource,
    LinkStatus,
    LinkTag,
    ManualPriority,
    ResearchReport,
    Tag,
    User,
)
from db.session import get_sessionmaker
from shared.tag_normalizer import normalize_tags
from worker.llm import normalize_area
from worker.priority import POPULAR_MIN_SOURCE_COUNT, POPULAR_MIN_UNIQUE_SENDERS


def _require_workspace(workspace_id: int | None) -> int:
    if workspace_id is None:
        raise HTTPException(401, "Not logged in")
    return workspace_id


router = APIRouter(prefix="/api/links", tags=["links"])

PAGE_SIZE = 20
# Потолок для действия «применить ко всей выборке». Не «без ограничения»:
# запрос должен оставаться одним обозримым UPDATE, а не подвисать на базе,
# в которой десятки тысяч ссылок.
BULK_ALL_LIMIT = 1000
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

# Режимы каталога. Это пресеты поверх того же query_links(), а не отдельные
# запросы: режим сужает выборку и задаёт сортировку по умолчанию, а все
# фильтры (тег, area, чат, автор, поиск) продолжают работать поверх него.
# "inbox" — то, что ещё никто не разбирал; смысл каталога в том, чтобы эта
# стопка не росла молча.
CATALOG_MODES = ("inbox", "all", "tested", "popular", "hidden")
DEFAULT_MODE = "inbox"
MODE_DEFAULT_SORT = {
    "inbox": "date",
    "all": "date",
    "tested": "date",
    "popular": "clicks",
    "hidden": "date",
}


def _wants_html(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def _current_mode(request: Request) -> str:
    """Режим каталога, из которого пришёл HTMX-запрос.

    HTMX присылает адрес текущей страницы в HX-Current-URL, поэтому режим
    не нужно протаскивать параметром через каждый PATCH: он описывает
    состояние экрана, а не операцию над ссылкой.
    """
    current_url = request.headers.get("hx-current-url")
    if not current_url:
        return DEFAULT_MODE
    mode = parse_qs(urlparse(current_url).query).get("mode", [DEFAULT_MODE])[0]
    return mode if mode in CATALOG_MODES else DEFAULT_MODE


@dataclass
class LinkListResult:
    items: list[Link]
    total: int
    page: int
    page_size: int


async def query_links(
    session: AsyncSession,
    *,
    workspace_id: int,
    mode: str = DEFAULT_MODE,
    tag: str | None = None,
    area: str | None = None,
    chat: str | None = None,
    sender: str | None = None,
    q: str | None = None,
    source_type: str | None = None,
    broken: bool = False,
    sort: str | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> LinkListResult:
    """Один запрос под весь каталог: режим сужает выборку, фильтры работают
    поверх любого режима. Отдельных «страниц» под Inbox/Popular/Hidden нет
    намеренно — иначе фильтры пришлось бы дублировать в каждой."""
    if mode not in CATALOG_MODES:
        mode = DEFAULT_MODE

    conditions = [Link.workspace_id == workspace_id]

    # Скрытое видно только в своём режиме — в остальных его нет нигде,
    # включая Inbox: спрятанное уже разобрали тем, что спрятали.
    if mode == "hidden":
        conditions.append(Link.is_hidden.is_(True))
    else:
        conditions.append(Link.is_hidden.is_(False))

    if mode == "inbox":
        conditions.append(Link.reviewed_at.is_(None))
    elif mode == "tested":
        conditions.append(Link.is_tested.is_(True))
    elif mode == "popular":
        # Популярное — это либо повторы (кинули несколько человек или
        # несколько раз), либо открытия с дашборда. Пороги те же, что у
        # worker.priority.is_popular и бейджа на карточке.
        conditions.append(
            or_(
                Link.unique_senders >= POPULAR_MIN_UNIQUE_SENDERS,
                Link.source_count >= POPULAR_MIN_SOURCE_COUNT,
                Link.click_count >= POPULAR_CLICKS_THRESHOLD,
            )
        )

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
    if sender:
        conditions.append(
            Link.id.in_(select(LinkSource.link_id).where(LinkSource.sender_name == sender))
        )
    if source_type:
        conditions.append(
            Link.id.in_(select(LinkSource.link_id).where(LinkSource.source_type == source_type))
        )
    if broken:
        # Ссылки, которые не удалось загрузить, иначе не найти: они выглядят
        # как обычные записи без описания и тегов, и сломанный источник
        # молча оседает в каталоге.
        conditions.append(Link.status.in_([LinkStatus.failed, LinkStatus.fetch_failed]))
    if q:
        like = f"%{q}%"
        conditions.append(
            or_(
                Link.title.ilike(like),
                Link.description.ilike(like),
                Link.url.ilike(like),
                # Ищем и по тому, что человек написал, кидая ссылку: часто
                # вспоминаешь именно реплику («Боря писал про очереди»), а не
                # заголовок статьи.
                Link.id.in_(select(LinkSource.link_id).where(LinkSource.message_text.ilike(like))),
            )
        )

    order = SORT_COLUMNS.get(sort or MODE_DEFAULT_SORT.get(mode, "date"), SORT_COLUMNS["date"])
    base_stmt = select(Link).where(*conditions)

    total = (
        await session.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()

    items_stmt = (
        base_stmt.options(selectinload(Link.tags), selectinload(Link.sources))
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await session.execute(items_stmt)).scalars().unique().all())

    return LinkListResult(items=items, total=total, page=page, page_size=page_size)


async def catalog_mode_counts(session: AsyncSession, workspace_id: int) -> dict[str, int]:
    """Счётчики для вкладок режимов — одним запросом с условными агрегатами,
    а не пятью. Число рядом с Inbox — единственное, что заставляет разбирать
    стопку; без него режим легко не заметить."""
    visible = Link.is_hidden.is_(False)
    popular = or_(
        Link.unique_senders >= POPULAR_MIN_UNIQUE_SENDERS,
        Link.source_count >= POPULAR_MIN_SOURCE_COUNT,
        Link.click_count >= POPULAR_CLICKS_THRESHOLD,
    )
    row = (
        await session.execute(
            select(
                func.count().filter(visible & Link.reviewed_at.is_(None)),
                func.count().filter(visible),
                func.count().filter(visible & Link.is_tested.is_(True)),
                func.count().filter(visible & popular),
                func.count().filter(Link.is_hidden.is_(True)),
            ).where(Link.workspace_id == workspace_id)
        )
    ).one()
    return dict(zip(CATALOG_MODES, row, strict=True))


async def get_latest_digest(
    session: AsyncSession, workspace_id: int, theme: str
) -> Collection | None:
    return await session.scalar(
        select(Collection)
        .where(Collection.workspace_id == workspace_id, Collection.theme == theme)
        .order_by(Collection.created_at.desc())
        .limit(1)
    )


async def list_digest_history(
    session: AsyncSession, workspace_id: int, theme: str, *, offset: int = 0, limit: int = 10
) -> list[Collection]:
    return list(
        (
            await session.execute(
                select(Collection)
                .where(Collection.workspace_id == workspace_id, Collection.theme == theme)
                .order_by(Collection.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def list_digest_history_combined(
    session: AsyncSession, workspace_id: int, themes: list[str], *, offset: int = 0, limit: int = 10
) -> list[Collection]:
    """Daily+weekly дайджесты в одной вкладке (F) — общая лента обеих тем,
    отсортированная по дате, тег Daily/Weekly проставляется в шаблоне по
    collection.theme."""
    return list(
        (
            await session.execute(
                select(Collection)
                .where(Collection.workspace_id == workspace_id, Collection.theme.in_(themes))
                .order_by(Collection.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def count_digest_history(session: AsyncSession, workspace_id: int, themes: list[str]) -> int:
    """Общее число выпусков — используется для нумерации issue (No. 001, ...)
    на странице /digest в стиле репорта: самый старый выпуск — No. 1."""
    return (
        await session.scalar(
            select(func.count())
            .select_from(Collection)
            .where(Collection.workspace_id == workspace_id, Collection.theme.in_(themes))
        )
    ) or 0


async def list_all_tags(session: AsyncSession, workspace_id: int) -> list[tuple[str, int]]:
    stmt = (
        select(Tag.name, func.count(LinkTag.link_id))
        .join(LinkTag, LinkTag.tag_id == Tag.id)
        .where(Tag.workspace_id == workspace_id)
        .group_by(Tag.name)
        .order_by(Tag.name)
    )
    return list((await session.execute(stmt)).all())


async def get_report_link_ids(
    session: AsyncSession, workspace_id: int, link_ids: list[int]
) -> set[int]:
    """По каким ссылкам уже собирали research-отчёт.

    Отчёт стоит денег и минут, и «мы это уже исследовали» — ровно то, что
    нужно знать до того, как нажать «собрать отчёт» второй раз."""
    if not link_ids:
        return set()
    rows = await session.execute(
        select(ResearchReport.link_id).where(
            ResearchReport.workspace_id == workspace_id,
            ResearchReport.link_id.in_(link_ids),
        )
    )
    return {row[0] for row in rows}


async def get_user_names(session: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    """Имена по id — для подписей «добавил» и «разобрал».

    «Разобрано» без автора превращается в состояние, за которое никто не
    отвечает, поэтому имя показывается рядом."""
    ids = [uid for uid in user_ids if uid]
    if not ids:
        return {}
    rows = await session.execute(
        select(User.id, User.full_name, User.username).where(User.id.in_(ids))
    )
    return {row[0]: (row[1] or row[2] or f"#{row[0]}") for row in rows}


async def list_all_areas(session: AsyncSession, workspace_id: int) -> list[tuple[str, int]]:
    """Area со счётчиками. В сайдбаре чип без числа бесполезен: он не
    отвечает на «есть ли там что-нибудь» до нажатия."""
    stmt = (
        select(Link.area, func.count())
        .where(Link.workspace_id == workspace_id, Link.area.is_not(None))
        .group_by(Link.area)
        .order_by(func.count().desc())
    )
    return list((await session.execute(stmt)).all())


async def count_broken(session: AsyncSession, workspace_id: int) -> int:
    """Сколько ссылок не удалось загрузить. Ноль — значит фильтр можно не
    показывать вовсе."""
    return (
        await session.scalar(
            select(func.count())
            .select_from(Link)
            .where(
                Link.workspace_id == workspace_id,
                Link.is_hidden.is_(False),
                Link.status.in_([LinkStatus.failed, LinkStatus.fetch_failed]),
            )
        )
    ) or 0


async def last_capture_at(session: AsyncSession, workspace_id: int) -> datetime | None:
    """Когда в каталог последний раз что-то приехало.

    Каталог наполняет бот, а не пользователь, поэтому тишина здесь значит
    либо что в чатах ничего не кидали, либо что сломался приём — и второе
    должно быть заметно, а не выясняться через неделю."""
    return await session.scalar(
        select(func.max(Link.created_at)).where(Link.workspace_id == workspace_id)
    )


async def list_all_chats(session: AsyncSession, workspace_id: int) -> list[tuple[str, int]]:
    """Чаты, из которых вообще что-то приходило, со счётчиками. Фильтр по
    чату уже умел query_links(), но выбрать чат в интерфейсе было нельзя —
    список неоткуда было взять."""
    stmt = (
        select(LinkSource.chat_title, func.count(func.distinct(LinkSource.link_id)))
        .join(Link, Link.id == LinkSource.link_id)
        .where(Link.workspace_id == workspace_id, LinkSource.chat_title.is_not(None))
        .group_by(LinkSource.chat_title)
        .order_by(func.count(func.distinct(LinkSource.link_id)).desc())
    )
    return list((await session.execute(stmt)).all())


async def list_all_senders(session: AsyncSession, workspace_id: int) -> list[tuple[str, int]]:
    """Кто вообще кидает ссылки, со счётчиками — «покажи, что приносил Боря»
    это нормальный способ искать в командной базе."""
    stmt = (
        select(LinkSource.sender_name, func.count(func.distinct(LinkSource.link_id)))
        .join(Link, Link.id == LinkSource.link_id)
        .where(Link.workspace_id == workspace_id, LinkSource.sender_name.is_not(None))
        .group_by(LinkSource.sender_name)
        .order_by(func.count(func.distinct(LinkSource.link_id)).desc())
    )
    return list((await session.execute(stmt)).all())


# Какие параметры каталога вообще имеет смысл сохранять в вид. Страница
# сюда не входит осознанно: вид — это «что показывать», а не «где я
# остановился».
VIEW_PARAM_KEYS = ("mode", "tag", "area", "chat", "sender", "q", "sort")


async def list_catalog_views(session: AsyncSession, workspace_id: int) -> list[CatalogView]:
    return list(
        (
            await session.execute(
                select(CatalogView)
                .where(CatalogView.workspace_id == workspace_id)
                .order_by(CatalogView.name)
            )
        )
        .scalars()
        .all()
    )


async def get_link_detail(session: AsyncSession, workspace_id: int, link_id: int) -> Link | None:
    link = await session.get(Link, link_id)
    if link is None or link.workspace_id != workspace_id:
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
    reviewed_at: datetime | None
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
            reviewed_at=link.reviewed_at,
            tags=[t.name for t in link.tags],
            created_at=link.created_at,
        )


async def _card_swap_response(
    request: Request,
    session: AsyncSession,
    workspace_id: int,
    link: Link,
    *,
    mode: str | None,
    drop: bool,
):
    """HTML-ответ на изменение состояния карточки в списке."""
    posts_by_link = await get_posts_by_link_ids(session, workspace_id, [link.id])
    mode_counts = await catalog_mode_counts(session, workspace_id)
    return templates.TemplateResponse(
        request,
        "_link_card_swap.html",
        {
            "link": link,
            "posts_by_link": posts_by_link,
            "drop": drop,
            "oob": True,
            "mode": mode or DEFAULT_MODE,
            "modes": CATALOG_MODES,
            "mode_counts": mode_counts,
        },
    )


async def _get_owned_link(session: AsyncSession, workspace_id: int, link_id: int) -> Link:
    link = await session.get(Link, link_id)
    if link is None or link.workspace_id != workspace_id:
        raise HTTPException(404, "Link not found")
    return link


@router.get("")
async def list_links_api(
    tag: str | None = None,
    chat: str | None = None,
    q: str | None = None,
    sort: str = "date",
    page: int = 1,
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    workspace_id = _require_workspace(workspace_id)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(
            session, workspace_id=workspace_id, tag=tag, chat=chat, q=q, sort=sort, page=page
        )
    return {
        "items": [LinkOut.from_link(link).model_dump(mode="json") for link in result.items],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
    }


@router.get("/{link_id}")
async def get_link_api(link_id: int, workspace_id: int | None = Depends(get_current_workspace_id)):
    workspace_id = _require_workspace(workspace_id)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, workspace_id, link_id)
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
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Общая функция редактирования записи: заголовок, описание, теги, area,
    ручной приоритет, отметка "оттестировано" — заменяет старый
    узкоспециализированный PATCH .../tags. view=card|detail определяет, какой
    HTML-фрагмент вернуть (карточка в списке или блок на странице ссылки) —
    сам PATCH и модель данных при этом общие."""
    workspace_id = _require_workspace(workspace_id)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await _get_owned_link(session, workspace_id, link_id)

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
            existing_tag = await session.scalar(
                select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == name)
            )
            if existing_tag is None:
                existing_tag = Tag(workspace_id=workspace_id, name=name, slug=name)
                session.add(existing_tag)
                await session.flush()
            session.add(LinkTag(link_id=link_id, tag_id=existing_tag.id))
        await session.commit()
        await session.refresh(link, attribute_names=["tags", "sources"])

        if _wants_html(request):
            if view == "detail":
                posts_by_link = await get_posts_by_link_ids(session, workspace_id, [link.id])
                return templates.TemplateResponse(
                    request,
                    "_link_detail_view.html",
                    {"link": link, "posts_by_link": posts_by_link},
                )
            mode = _current_mode(request)
            return await _card_swap_response(
                request,
                session,
                workspace_id,
                link,
                mode=mode,
                # Правка могла сменить area/теги, но не то, в каком
                # режиме запись лежит — кроме tested.
                drop=(mode == "tested" and not link.is_tested),
            )
        return LinkOut.from_link(link).model_dump(mode="json")


@router.patch("/{link_id}/priority")
async def update_link_priority(
    link_id: int,
    request: Request,
    priority: str = Form(...),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Inline-редактирование Priority прямо в строке таблицы (select с
    hx-trigger=change) — трогает только это поле, в отличие от update_link,
    которому нужна вся форма редактирования целиком."""
    workspace_id = _require_workspace(workspace_id)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await _get_owned_link(session, workspace_id, link_id)
        if priority not in (p.value for p in ManualPriority):
            raise HTTPException(422, "Invalid priority")
        link.manual_priority = ManualPriority(priority)
        await session.commit()
        await session.refresh(link, attribute_names=["tags", "sources"])

        if _wants_html(request):
            return await _card_swap_response(
                request,
                session,
                workspace_id,
                link,
                mode=_current_mode(request),
                drop=False,
            )
        return LinkOut.from_link(link).model_dump(mode="json")


@router.patch("/{link_id}/tested")
async def update_link_tested(
    link_id: int,
    request: Request,
    tested: bool = Form(False),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Inline-редактирование Tested прямо в строке таблицы (чекбокс с
    hx-trigger=change) — снятая галочка не шлёт значение в форме, поэтому
    default=False корректно отражает "unchecked"."""
    workspace_id = _require_workspace(workspace_id)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await _get_owned_link(session, workspace_id, link_id)
        link.is_tested = tested
        await session.commit()
        await session.refresh(link, attribute_names=["tags", "sources"])

        if _wants_html(request):
            mode = _current_mode(request)
            return await _card_swap_response(
                request,
                session,
                workspace_id,
                link,
                mode=mode,
                drop=(mode == "tested" and not tested),
            )
        return LinkOut.from_link(link).model_dump(mode="json")


BULK_ACTIONS = ("reviewed", "unreviewed", "hide", "unhide", "tested", "untested", "priority")


@router.post("/views")
async def save_catalog_view(
    request: Request,
    name: str = Form(...),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Сохранить текущий набор фильтров под именем.

    Вид общий для workspace, а не личный: «что тестировать» — это про
    команду, и держать у каждого свою копию значило бы, что договорённости
    нет."""
    workspace_id = _require_workspace(workspace_id)
    name = name.strip()
    if not name:
        raise HTTPException(422, "Название вида не может быть пустым")

    params = {
        key: value
        for key, value in request.query_params.items()
        if key in VIEW_PARAM_KEYS and value
    }
    user = await get_current_user(request)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        existing = await session.scalar(
            select(CatalogView).where(
                CatalogView.workspace_id == workspace_id, CatalogView.name == name
            )
        )
        # Одноимённый вид перезаписывается, а не падает уникальным
        # индексом: «сохранить под тем же именем» читается как «обновить».
        if existing is not None:
            existing.params_json = params
        else:
            session.add(
                CatalogView(
                    workspace_id=workspace_id,
                    name=name,
                    params_json=params,
                    created_by_user_id=user.id if user else None,
                )
            )
        await session.commit()
        views = await list_catalog_views(session, workspace_id)

    return templates.TemplateResponse(
        request,
        "_catalog_views.html",
        {"views": views, "saved_name": name, "filters": params, "mode": params.get("mode")},
    )


@router.delete("/views/{view_id}")
async def delete_catalog_view(
    request: Request,
    view_id: int,
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    workspace_id = _require_workspace(workspace_id)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        view = await session.get(CatalogView, view_id)
        if view is None or view.workspace_id != workspace_id:
            raise HTTPException(404, "Вид не найден")
        await session.delete(view)
        await session.commit()
        views = await list_catalog_views(session, workspace_id)

    return templates.TemplateResponse(
        request, "_catalog_views.html", {"views": views, "filters": {}, "mode": None}
    )


@router.post("/bulk")
async def bulk_update_links(
    request: Request,
    action: str = Form(...),
    priority: str = Form(""),
    scope: str = Form("selected"),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Массовое действие над выбранными записями либо над всей текущей выборкой.

    scope="all" нужен ровно из-за одной ситуации: миграция намеренно не
    проставляла reviewed_at задним числом, поэтому в Inbox сразу лежит всё,
    что накопилось раньше. Разбирать это по одной записи бессмысленно, а
    подделать разбор в миграции — нечестно; правильное место для решения
    «этого мы не разбирали и разбирать не будем» — кнопка, которую нажал
    человек.
    """
    workspace_id = _require_workspace(workspace_id)
    if action not in BULK_ACTIONS:
        raise HTTPException(422, "Unknown bulk action")

    user = await get_current_user(request)
    mode = _current_mode(request)
    params = dict(request.query_params)
    # Галочки приходят повторяющимся полем ids, поэтому читаем список из
    # формы, а не объявляем list-параметр: параметр с изменяемым типом в
    # значении по умолчанию ловит B008, а getlist к тому же честнее
    # описывает, что пришло от клиента. Нечисловое молча отбрасываем —
    # это данные из браузера, а не аргумент внутреннего вызова.
    ids = [int(value) for value in (await request.form()).getlist("ids") if str(value).isdigit()]

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        if scope == "all":
            # Вся текущая выборка, а не только текущая страница: кнопка
            # обещает «всё в этом фильтре».
            selection = await query_links(
                session,
                workspace_id=workspace_id,
                mode=mode,
                tag=params.get("tag"),
                area=params.get("area"),
                chat=params.get("chat"),
                sender=params.get("sender"),
                q=params.get("q"),
                page=1,
                page_size=BULK_ALL_LIMIT,
            )
            targets = selection.items
        else:
            targets = list(
                (
                    await session.execute(
                        # Скоуп по workspace здесь не формальность: ids
                        # приходят из формы, то есть от клиента, и без него
                        # чужую запись можно было бы тронуть по номеру.
                        select(Link).where(
                            Link.workspace_id == workspace_id, Link.id.in_(ids or [-1])
                        )
                    )
                )
                .scalars()
                .all()
            )

        now = datetime.now(UTC)
        for link in targets:
            if action == "reviewed":
                link.reviewed_at = now
                link.reviewed_by_user_id = user.id if user else None
            elif action == "unreviewed":
                link.reviewed_at = None
                link.reviewed_by_user_id = None
            elif action == "hide":
                link.is_hidden = True
            elif action == "unhide":
                link.is_hidden = False
            elif action == "tested":
                link.is_tested = True
            elif action == "untested":
                link.is_tested = False
            elif action == "priority":
                if priority not in (p.value for p in ManualPriority):
                    raise HTTPException(422, "Invalid priority")
                link.manual_priority = ManualPriority(priority)
        await session.commit()

        result = await query_links(
            session,
            workspace_id=workspace_id,
            mode=mode,
            tag=params.get("tag"),
            area=params.get("area"),
            chat=params.get("chat"),
            sender=params.get("sender"),
            q=params.get("q"),
            sort=params.get("sort"),
            page=1,
        )
        posts_by_link = await get_posts_by_link_ids(
            session, workspace_id, [link.id for link in result.items]
        )
        mode_counts = await catalog_mode_counts(session, workspace_id)

    filters = {"mode": mode}
    for key in ("tag", "area", "chat", "sender", "q", "sort"):
        if params.get(key):
            filters[key] = params[key]

    return templates.TemplateResponse(
        request,
        "_links_list.html",
        {
            "links": result.items,
            "posts_by_link": posts_by_link,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "mode": mode,
            "modes": CATALOG_MODES,
            "mode_counts": mode_counts,
            "filters": filters,
            "bulk_applied": len(targets),
            "oob": True,
        },
    )


@router.patch("/{link_id}/reviewed")
async def update_link_reviewed(
    link_id: int,
    request: Request,
    reviewed: bool = Query(True),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Отметить ссылку разобранной (убрать из Inbox) или вернуть обратно.

    Пишем и время, и кто разобрал: «разобрано» без автора превращается в
    состояние, за которое никто не отвечает."""
    workspace_id = _require_workspace(workspace_id)
    mode = _current_mode(request)
    user = await get_current_user(request)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await _get_owned_link(session, workspace_id, link_id)
        link.reviewed_at = datetime.now(UTC) if reviewed else None
        link.reviewed_by_user_id = user.id if (reviewed and user) else None
        await session.commit()
        await session.refresh(link, attribute_names=["tags", "sources"])

        if _wants_html(request):
            return await _card_swap_response(
                request,
                session,
                workspace_id,
                link,
                mode=mode,
                # Разобранному в Inbox там больше не место.
                drop=(mode == "inbox" and reviewed),
            )
        return LinkOut.from_link(link).model_dump(mode="json")


@router.patch("/{link_id}/hide")
async def update_hide(
    link_id: int,
    request: Request,
    hidden: bool = Query(True),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    workspace_id = _require_workspace(workspace_id)
    mode = _current_mode(request)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await _get_owned_link(session, workspace_id, link_id)
        link.is_hidden = hidden
        await session.commit()
        await session.refresh(link, attribute_names=["tags", "sources"])

        if _wants_html(request):
            return await _card_swap_response(
                request,
                session,
                workspace_id,
                link,
                mode=mode,
                # Скрытое пропадает из любого видимого режима, а возвращённое —
                # из режима «Скрытое»: в обоих случаях запись переехала.
                drop=(hidden and mode != "hidden") or (not hidden and mode == "hidden"),
            )
        return {"id": link_id, "is_hidden": hidden}
