from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, text

from api.routes import ask, collections, links, research
from api.routes.links import (
    find_similar_links,
    get_latest_daily_top3,
    get_link_detail,
    list_all_tags,
    query_links,
)
from api.templates_env import templates
from db.models import Collection, Link, ResearchReport
from db.session import get_sessionmaker
from shared.config import get_settings
from worker.rag import answer_question
from worker.tasks import add_research_links, generate_research_report

app = FastAPI(title="Nova-260")

app.include_router(links.router)
app.include_router(collections.router)
app.include_router(research.router)
app.include_router(ask.router)


@app.get("/health")
async def health() -> dict:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    tag: str | None = None,
    chat: str | None = None,
    q: str | None = None,
    sort: str = "priority",
    page: int = 1,
):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(session, tag=tag, chat=chat, q=q, sort=sort, page=page)
        top3_collection, top3_links = await get_latest_daily_top3(session)
        all_tags = await list_all_tags(session)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "links": result.items,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "tag": tag,
            "chat": chat,
            "q": q,
            "sort": sort,
            "top3_collection": top3_collection,
            "top3_links": top3_links,
            "all_tags": all_tags,
        },
    )


@app.get("/partials/links", response_class=HTMLResponse)
async def partial_links(
    request: Request,
    tag: str | None = None,
    chat: str | None = None,
    q: str | None = None,
    sort: str = "priority",
    page: int = 1,
):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(session, tag=tag, chat=chat, q=q, sort=sort, page=page)

    return templates.TemplateResponse(
        request,
        "_links_list.html",
        {
            "links": result.items,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "tag": tag,
            "chat": chat,
            "q": q,
            "sort": sort,
        },
    )


@app.post("/ask", response_class=HTMLResponse)
async def ask_dashboard(request: Request, question: str = Form(...)):
    """HTMX-виджет «Спросить базу» на дашборде (F-80). JSON-контракт для
    внешней интеграции — отдельно, POST /api/ask (api/routes/ask.py)."""
    result = await answer_question(question)
    return templates.TemplateResponse(request, "_ask_result.html", {"result": result})


@app.get("/links/{link_id}", response_class=HTMLResponse)
async def link_detail_page(request: Request, link_id: int):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        return HTMLResponse("Ссылка не найдена", status_code=404)
    return templates.TemplateResponse(request, "link.html", {"link": link})


@app.get("/links/{link_id}/visit")
async def visit_link(link_id: int):
    """Считает переход по ссылке (метрика популярности на дашборде) и
    редиректит на реальный URL."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            return HTMLResponse("Ссылка не найдена", status_code=404)
        link.click_count += 1
        target_url = link.url
        await session.commit()
    return RedirectResponse(target_url, status_code=302)


@app.get("/links/{link_id}/card", response_class=HTMLResponse)
async def link_card_view(request: Request, link_id: int):
    """Карточка в режиме просмотра — используется кнопкой «Отмена» в форме
    редактирования, чтобы вернуться без сохранения."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        return HTMLResponse("Ссылка не найдена", status_code=404)
    return templates.TemplateResponse(request, "_link_card.html", {"link": link})


@app.get("/links/{link_id}/detail-view", response_class=HTMLResponse)
async def link_detail_view_fragment(request: Request, link_id: int):
    """Блок заголовок/описание/теги на странице ссылки в режиме просмотра —
    используется кнопкой «Отмена» в форме редактирования."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        return HTMLResponse("Ссылка не найдена", status_code=404)
    return templates.TemplateResponse(request, "_link_detail_view.html", {"link": link})


@app.get("/links/{link_id}/detail-edit-form", response_class=HTMLResponse)
async def link_detail_edit_form(request: Request, link_id: int):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        return HTMLResponse("Ссылка не найдена", status_code=404)
    return templates.TemplateResponse(request, "_link_detail_edit.html", {"link": link})


@app.get("/links/{link_id}/edit-form", response_class=HTMLResponse)
async def link_edit_form(request: Request, link_id: int):
    """Общая форма редактирования записи: заголовок, описание, теги.
    Сохранение идёт через PATCH /api/links/{id} (api/routes/links.py)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        return HTMLResponse("Ссылка не найдена", status_code=404)
    return templates.TemplateResponse(request, "_link_card_edit.html", {"link": link})


@app.get("/links/{link_id}/similar", response_class=HTMLResponse)
async def similar_links(request: Request, link_id: int):
    """Похожие ссылки в своей базе по embedding — без LLM, векторный поиск."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            return HTMLResponse("Ссылка не найдена", status_code=404)
        similar = await find_similar_links(session, link)
    return templates.TemplateResponse(request, "_similar_links.html", {"similar": similar})


async def _latest_research_report(session, link_id: int) -> ResearchReport | None:
    return await session.scalar(
        select(ResearchReport)
        .where(ResearchReport.link_id == link_id)
        .order_by(ResearchReport.created_at.desc())
    )


@app.post("/links/{link_id}/research", response_class=HTMLResponse)
async def start_research(request: Request, link_id: int):
    """F-58/F-60: запуск research-отчёта из дашборда (не автоматически)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            return HTMLResponse("Ссылка не найдена", status_code=404)
        existing = await _latest_research_report(session, link_id)
    if existing is None:
        generate_research_report.delay(link_id)  # F-62: кэш — не перегенерирует, если уже есть
    return templates.TemplateResponse(
        request, "_research_status.html", {"link_id": link_id, "report": existing}
    )


@app.get("/links/{link_id}/research/status", response_class=HTMLResponse)
async def research_status(request: Request, link_id: int):
    """F-64: поллинг прогресса («ищу… пишу отчёт…»)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        report = await _latest_research_report(session, link_id)
    return templates.TemplateResponse(
        request, "_research_status.html", {"link_id": link_id, "report": report}
    )


@app.post("/research/{research_id}/add-links", response_class=HTMLResponse)
async def add_links_from_research_dashboard(research_id: int):
    """F-65: добавить найденные research-ссылки в основную базу."""
    add_research_links.delay(research_id)
    return HTMLResponse("<p>Ссылки добавляются в базу…</p>")


_COLLECTION_DAYS_RU = {
    "mon": "понедельникам",
    "tue": "вторникам",
    "wed": "средам",
    "thu": "четвергам",
    "fri": "пятницам",
    "sat": "субботам",
    "sun": "воскресеньям",
}


@app.get("/collections", response_class=HTMLResponse)
async def collections_page(request: Request):
    """F-74: раздел «Подборки»."""
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(Collection)
                    .where(Collection.theme != "daily-top3")
                    .order_by(Collection.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    day_ru = _COLLECTION_DAYS_RU.get(settings.collection_cron_day, settings.collection_cron_day)
    schedule_note = (
        f"Новые подборки собираются по {day_ru} в {settings.collection_cron_hour:02d}:00."
    )

    return templates.TemplateResponse(
        request, "collections.html", {"collections": rows, "schedule_note": schedule_note}
    )
