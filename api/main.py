from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from api.changelog import CHANGELOG, CURRENT_VERSION
from api.routes import ask, collections, links, research
from api.routes.links import get_link_detail, list_all_tags, list_digest_history, query_links
from api.templates_env import templates
from bot.formatting import format_qa_reply_html, render_markdown_links_html
from db.models import Collection, Link, ResearchReport
from db.session import get_sessionmaker
from shared.config import get_settings
from worker.collections import DAILY_DIGEST_THEME, WEEKLY_DIGEST_THEME
from worker.rag import answer_question
from worker.tasks import add_research_links, generate_research_report

app = FastAPI(title="Nova-260")
app.mount("/static", StaticFiles(directory="api/static"), name="static")

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
    sort: str = "priority",
    page: int = 1,
):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(session, tag=tag, sort=sort, page=page)
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
            "sort": sort,
            "all_tags": all_tags,
        },
    )


@app.get("/partials/links", response_class=HTMLResponse)
async def partial_links(
    request: Request,
    tag: str | None = None,
    sort: str = "priority",
    page: int = 1,
):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(session, tag=tag, sort=sort, page=page)

    return templates.TemplateResponse(
        request,
        "_links_list.html",
        {
            "links": result.items,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "tag": tag,
            "sort": sort,
        },
    )


@app.post("/ask", response_class=HTMLResponse)
async def ask_dashboard(request: Request, question: str = Form(...)):
    """HTMX-виджет «Спросить базу» на дашборде (F-80). JSON-контракт для
    внешней интеграции — отдельно, POST /api/ask (api/routes/ask.py)."""
    result = await answer_question(question)
    answer_html = format_qa_reply_html(result)
    return templates.TemplateResponse(request, "_ask_result.html", {"answer_html": answer_html})


@app.get("/links/{link_id}", response_class=HTMLResponse)
async def link_detail_page(request: Request, link_id: int):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        return HTMLResponse("Link not found", status_code=404)
    return templates.TemplateResponse(request, "link.html", {"link": link})


@app.get("/links/{link_id}/visit")
async def visit_link(link_id: int):
    """Считает переход по ссылке (метрика популярности на дашборде) и
    редиректит на реальный URL."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            return HTMLResponse("Link not found", status_code=404)
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
        return HTMLResponse("Link not found", status_code=404)
    return templates.TemplateResponse(request, "_link_card.html", {"link": link})


@app.get("/links/{link_id}/detail-view", response_class=HTMLResponse)
async def link_detail_view_fragment(request: Request, link_id: int):
    """Блок заголовок/описание/теги на странице ссылки в режиме просмотра —
    используется кнопкой «Отмена» в форме редактирования."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        return HTMLResponse("Link not found", status_code=404)
    return templates.TemplateResponse(request, "_link_detail_view.html", {"link": link})


@app.get("/links/{link_id}/detail-edit-form", response_class=HTMLResponse)
async def link_detail_edit_form(request: Request, link_id: int):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        return HTMLResponse("Link not found", status_code=404)
    return templates.TemplateResponse(request, "_link_detail_edit.html", {"link": link})


@app.get("/links/{link_id}/edit-form", response_class=HTMLResponse)
async def link_edit_form(request: Request, link_id: int):
    """Общая форма редактирования записи: заголовок, описание, теги.
    Сохранение идёт через PATCH /api/links/{id} (api/routes/links.py)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, link_id)
    if link is None:
        return HTMLResponse("Link not found", status_code=404)
    return templates.TemplateResponse(request, "_link_card_edit.html", {"link": link})


async def _latest_research_report(session, link_id: int) -> ResearchReport | None:
    return await session.scalar(
        select(ResearchReport)
        .where(ResearchReport.link_id == link_id)
        .order_by(ResearchReport.created_at.desc())
    )


def _research_status_context(link_id: int, report: ResearchReport | None) -> dict:
    context = {"link_id": link_id, "report": report}
    if report is not None:
        context["report_html"] = render_markdown_links_html(report.report_md)
    return context


@app.post("/links/{link_id}/research", response_class=HTMLResponse)
async def start_research(request: Request, link_id: int):
    """F-58/F-60: запуск research-отчёта из дашборда (не автоматически)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            return HTMLResponse("Link not found", status_code=404)
        existing = await _latest_research_report(session, link_id)
    if existing is None:
        generate_research_report.delay(link_id)  # F-62: кэш — не перегенерирует, если уже есть
    return templates.TemplateResponse(
        request, "_research_status.html", _research_status_context(link_id, existing)
    )


@app.get("/links/{link_id}/research/status", response_class=HTMLResponse)
async def research_status(request: Request, link_id: int):
    """F-64: поллинг прогресса («ищу… пишу отчёт…»)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        report = await _latest_research_report(session, link_id)
    return templates.TemplateResponse(
        request, "_research_status.html", _research_status_context(link_id, report)
    )


@app.get("/research/{research_id}/download")
async def download_research_report(research_id: int):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        report = await session.get(ResearchReport, research_id)
    if report is None:
        return HTMLResponse("Report not found", status_code=404)
    return Response(
        report.report_md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="research-{research_id}.md"'},
    )


@app.post("/research/{research_id}/add-links", response_class=HTMLResponse)
async def add_links_from_research_dashboard(research_id: int):
    """F-65: добавить найденные research-ссылки в основную базу."""
    add_research_links.delay(research_id)
    return HTMLResponse("<p>Adding links to the database…</p>")


_MSK = ZoneInfo("Europe/Moscow")


def _is_today_msk(dt: datetime) -> bool:
    return dt.astimezone(_MSK).date() == datetime.now(_MSK).date()


_WEEKDAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


@app.get("/daily-digest", response_class=HTMLResponse)
async def daily_digest_page(request: Request):
    """Автоматический ежедневный топ-10 свежих статей (Celery Beat, 12:00 МСК)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        history = await list_digest_history(session, DAILY_DIGEST_THEME, limit=30)

    return templates.TemplateResponse(
        request,
        "daily_digest.html",
        {"history": history, "is_today_msk": _is_today_msk},
    )


@app.get("/daily-digest/{digest_id}", response_class=HTMLResponse)
async def daily_digest_detail_page(request: Request, digest_id: int):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        collection = await session.get(Collection, digest_id)
    if collection is None or collection.theme != DAILY_DIGEST_THEME:
        return HTMLResponse("Digest not found", status_code=404)
    return templates.TemplateResponse(
        request, "digest_detail.html", {"collection": collection, "back_href": "/daily-digest"}
    )


@app.get("/weekly-digest", response_class=HTMLResponse)
async def weekly_digest_page(request: Request):
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        history = await list_digest_history(session, WEEKLY_DIGEST_THEME, limit=30)

    weekday = _WEEKDAY_NAMES.get(settings.collection_cron_day, settings.collection_cron_day)
    schedule_note = (
        f"New digests are collected every {weekday} at {settings.collection_cron_hour:02d}:00 MSK."
    )

    return templates.TemplateResponse(
        request,
        "weekly_digest.html",
        {"history": history, "schedule_note": schedule_note, "is_today_msk": _is_today_msk},
    )


@app.get("/weekly-digest/{digest_id}", response_class=HTMLResponse)
async def weekly_digest_detail_page(request: Request, digest_id: int):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        collection = await session.get(Collection, digest_id)
    if collection is None or collection.theme != WEEKLY_DIGEST_THEME:
        return HTMLResponse("Digest not found", status_code=404)
    return templates.TemplateResponse(
        request, "digest_detail.html", {"collection": collection, "back_href": "/weekly-digest"}
    )


@app.get("/changelog", response_class=HTMLResponse)
async def changelog_page(request: Request):
    return templates.TemplateResponse(
        request, "changelog.html", {"changelog": CHANGELOG, "current_version": CURRENT_VERSION}
    )
