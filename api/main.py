import hashlib
import html
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from starlette.middleware.sessions import SessionMiddleware

from api.changelog import CHANGELOG, CURRENT_VERSION
from api.export import links_to_csv, links_to_markdown, posts_to_csv, posts_to_markdown
from api.export_channels import channel_posts_to_csv, channel_posts_to_markdown
from api.deps import get_current_user, get_current_workspace_id
from api.routes import account as account_routes
from api.routes import ask, auth, collections, links, research
from api.routes import channels as channels_routes
from api.routes import posts as posts_routes
from api.routes.links import (
    get_link_detail,
    list_all_tags,
    list_digest_history_combined,
    query_links,
)
from api.routes.posts import get_posts_by_link_ids, list_all_post_tags, query_posts
from api.templates_env import templates
from bot.formatting import format_qa_reply_html, render_markdown_links_html
from bot.ingest import enqueue_post_processing, enqueue_processing, ingest_message
from db.models import (
    ChannelParsedPost,
    ChannelParseJob,
    ChannelVoiceReport,
    ChannelVoiceReportStatus,
    ChannelWatch,
    Collection,
    Invite,
    Link,
    Post,
    ResearchReport,
    SourceType,
    User,
    Workspace,
    WorkspaceMember,
)
from db.session import get_sessionmaker
from shared.config import get_settings
from worker.channel_scraper import normalize_channel_username
from worker.collections import DAILY_DIGEST_THEME, WEEKLY_DIGEST_THEME
from worker.fetcher import FetchError, fetch_metadata
from worker.rag import answer_question
from worker.tasks import add_research_links, generate_research_report, run_channel_parse_job

MANUAL_ADD_CHAT_ID = 0  # синтетический chat_id для ссылок, добавленных вручную с дашборда

app = FastAPI(title="Nova-260")
app.mount("/static", StaticFiles(directory="api/static"), name="static")
app.add_middleware(SessionMiddleware, secret_key=get_settings().session_secret_key)

app.include_router(links.router)
app.include_router(posts_routes.router)
app.include_router(collections.router)
app.include_router(research.router)
app.include_router(ask.router)
app.include_router(channels_routes.router)
app.include_router(auth.router)
app.include_router(account_routes.router)


def _require_workspace(workspace_id: int | None) -> int | RedirectResponse:
    """Волна 4 плана "Личный кабинет + workspace": каждый роут дашборда
    требует логина — незалогиненных и юзеров без workspace отправляем на
    /login (там же виден статус, если юзер залогинен, но без workspace —
    /account объясняет, что делать)."""
    if workspace_id is None:
        return RedirectResponse("/login")
    return workspace_id


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
    area: str | None = None,
    sort: str = "date",
    page: int = 1,
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(
            session, workspace_id=workspace_id, tag=tag, area=area, sort=sort, page=page
        )
        all_tags = await list_all_tags(session, workspace_id)
        posts_by_link = await get_posts_by_link_ids(
            session, workspace_id, [link.id for link in result.items]
        )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "links": result.items,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "tag": tag,
            "area": area,
            "sort": sort,
            "all_tags": all_tags,
            "posts_by_link": posts_by_link,
        },
    )


@app.get("/partials/links", response_class=HTMLResponse)
async def partial_links(
    request: Request,
    tag: str | None = None,
    area: str | None = None,
    sort: str = "date",
    page: int = 1,
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(
            session, workspace_id=workspace_id, tag=tag, area=area, sort=sort, page=page
        )
        posts_by_link = await get_posts_by_link_ids(
            session, workspace_id, [link.id for link in result.items]
        )

    return templates.TemplateResponse(
        request,
        "_links_list.html",
        {
            "links": result.items,
            "posts_by_link": posts_by_link,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "tag": tag,
            "area": area,
            "sort": sort,
        },
    )


@app.post("/links/add", response_class=HTMLResponse)
async def add_link_manual(
    request: Request,
    url: str = Form(...),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Ручное добавление ссылки с дашборда — идёт через тот же dedup/LLM
    пайплайн, что и ссылки из бота (bot/ingest.py), просто с синтетическим
    источником вместо реального Telegram-сообщения."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate
    current_user = await get_current_user(request)

    url = url.strip()
    if not url:
        status_text = "Enter a URL."
    else:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            raw_message, is_new = await ingest_message(
                session,
                workspace_id=workspace_id,
                chat_id=MANUAL_ADD_CHAT_ID,
                message_id=int(time.time() * 1000),
                sender_id=current_user.telegram_id if current_user else None,
                text=url,
                entities_json=None,
                source_type=SourceType.manual,
            )
        if is_new:
            enqueue_processing(raw_message.id)
            status_text = "Added — will appear in the table once processed (a few seconds)."
        else:
            status_text = "Already queued."

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_links(session, workspace_id=workspace_id, sort="date", page=1)
        posts_by_link = await get_posts_by_link_ids(
            session, workspace_id, [link.id for link in result.items]
        )

    list_response = templates.TemplateResponse(
        request,
        "_links_list.html",
        {
            "links": result.items,
            "posts_by_link": posts_by_link,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "tag": None,
            "area": None,
            "sort": "date",
        },
    )
    status_html = (
        f'<p id="add-link-status" hx-swap-oob="true" class="card-meta">'
        f"{html.escape(status_text)}</p>"
    )
    return HTMLResponse(list_response.body.decode() + status_html)


@app.post("/ask", response_class=HTMLResponse)
async def ask_dashboard(
    request: Request,
    question: str = Form(...),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """HTMX-виджет «Спросить базу» на дашборде (F-80). JSON-контракт для
    внешней интеграции — отдельно, POST /api/ask (api/routes/ask.py)."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    result = await answer_question(question, workspace_id=workspace_id)
    answer_html = format_qa_reply_html(result)
    return templates.TemplateResponse(request, "_ask_result.html", {"answer_html": answer_html})


@app.get("/links/{link_id}", response_class=HTMLResponse)
async def link_detail_page(
    request: Request, link_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, workspace_id, link_id)
    if link is None:
        return HTMLResponse("Link not found", status_code=404)
    return templates.TemplateResponse(request, "link.html", {"link": link})


@app.get("/links/{link_id}/visit")
async def visit_link(link_id: int, workspace_id: int | None = Depends(get_current_workspace_id)):
    """Считает переход по ссылке (метрика популярности на дашборде) и
    редиректит на реальный URL."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None or link.workspace_id != workspace_id:
            return HTMLResponse("Link not found", status_code=404)
        link.click_count += 1
        target_url = link.url
        await session.commit()
    return RedirectResponse(target_url, status_code=302)


@app.get("/links/{link_id}/card", response_class=HTMLResponse)
async def link_card_view(
    request: Request, link_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """Карточка в режиме просмотра — используется кнопкой «Отмена» в форме
    редактирования, чтобы вернуться без сохранения."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, workspace_id, link_id)
    if link is None:
        return HTMLResponse("Link not found", status_code=404)
    return templates.TemplateResponse(request, "_link_card.html", {"link": link})


@app.get("/links/{link_id}/detail-view", response_class=HTMLResponse)
async def link_detail_view_fragment(
    request: Request, link_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """Блок заголовок/описание/теги на странице ссылки в режиме просмотра —
    используется кнопкой «Отмена» в форме редактирования."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, workspace_id, link_id)
    if link is None:
        return HTMLResponse("Link not found", status_code=404)
    return templates.TemplateResponse(request, "_link_detail_view.html", {"link": link})


@app.get("/links/{link_id}/detail-edit-form", response_class=HTMLResponse)
async def link_detail_edit_form(
    request: Request, link_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, workspace_id, link_id)
    if link is None:
        return HTMLResponse("Link not found", status_code=404)
    return templates.TemplateResponse(request, "_link_detail_edit.html", {"link": link})


@app.get("/links/{link_id}/edit-form", response_class=HTMLResponse)
async def link_edit_form(
    request: Request, link_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """Общая форма редактирования записи: заголовок, описание, теги.
    Сохранение идёт через PATCH /api/links/{id} (api/routes/links.py)."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await get_link_detail(session, workspace_id, link_id)
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
async def start_research(
    request: Request, link_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """F-58/F-60: запуск research-отчёта из дашборда (не автоматически)."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None or link.workspace_id != workspace_id:
            return HTMLResponse("Link not found", status_code=404)
        existing = await _latest_research_report(session, link_id)
    if existing is None:
        generate_research_report.delay(link_id)  # F-62: кэш — не перегенерирует, если уже есть
    return templates.TemplateResponse(
        request, "_research_status.html", _research_status_context(link_id, existing)
    )


@app.get("/links/{link_id}/research/status", response_class=HTMLResponse)
async def research_status(
    request: Request, link_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """F-64: поллинг прогресса («ищу… пишу отчёт…»)."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None or link.workspace_id != workspace_id:
            return HTMLResponse("Link not found", status_code=404)
        report = await _latest_research_report(session, link_id)
    return templates.TemplateResponse(
        request, "_research_status.html", _research_status_context(link_id, report)
    )


@app.get("/research/{research_id}/download")
async def download_research_report(
    research_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        report = await session.get(ResearchReport, research_id)
    if report is None or report.workspace_id != workspace_id:
        return HTMLResponse("Report not found", status_code=404)
    return Response(
        report.report_md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="research-{research_id}.md"'},
    )


@app.post("/research/{research_id}/add-links", response_class=HTMLResponse)
async def add_links_from_research_dashboard(
    research_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """F-65: добавить найденные research-ссылки в основную базу."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        report = await session.get(ResearchReport, research_id)
    if report is None or report.workspace_id != workspace_id:
        return HTMLResponse("Report not found", status_code=404)
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


@app.get("/digest", response_class=HTMLResponse)
async def digest_page(
    request: Request, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """Daily (Celery Beat, 12:00 МСК) и weekly (расписание из settings) дайджесты
    в одной ленте — тег Daily/Weekly проставляется в шаблоне по collection.theme."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        history = await list_digest_history_combined(
            session, workspace_id, [DAILY_DIGEST_THEME, WEEKLY_DIGEST_THEME], limit=30
        )

    weekday = _WEEKDAY_NAMES.get(settings.collection_cron_day, settings.collection_cron_day)
    schedule_note = (
        f"Daily digests are collected every day at 12:00 MSK, weekly digests every "
        f"{weekday} at {settings.collection_cron_hour:02d}:00 MSK."
    )

    return templates.TemplateResponse(
        request,
        "digest.html",
        {"history": history, "schedule_note": schedule_note, "is_today_msk": _is_today_msk},
    )


@app.get("/digest/{digest_id}", response_class=HTMLResponse)
async def digest_detail_page(
    request: Request, digest_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        collection = await session.get(Collection, digest_id)
    if (
        collection is None
        or collection.workspace_id != workspace_id
        or collection.theme not in (DAILY_DIGEST_THEME, WEEKLY_DIGEST_THEME)
    ):
        return HTMLResponse("Digest not found", status_code=404)
    return templates.TemplateResponse(
        request, "digest_detail.html", {"collection": collection, "back_href": "/digest"}
    )


@app.get("/daily-digest")
async def daily_digest_redirect():
    return RedirectResponse("/digest", status_code=301)


@app.get("/daily-digest/{digest_id}")
async def daily_digest_detail_redirect(digest_id: int):
    return RedirectResponse(f"/digest/{digest_id}", status_code=301)


@app.get("/weekly-digest")
async def weekly_digest_redirect():
    return RedirectResponse("/digest", status_code=301)


@app.get("/weekly-digest/{digest_id}")
async def weekly_digest_detail_redirect(digest_id: int):
    return RedirectResponse(f"/digest/{digest_id}", status_code=301)


_CHANNEL_PARSE_FORM_DEFAULTS = {
    "channel_input": "",
    "post_limit": 50,
    "date_from": "",
    "date_to": "",
    "text_only": False,
    "skip_forwards": True,
    "min_text_length": 0,
    "collect_urls": False,
    "collect_commenters": False,
    "voice_dna": True,
}


@app.get("/channels/parse", response_class=HTMLResponse)
async def channel_parse_form(
    request: Request, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """Шаг 1 wizard'а Channel Parser (TZ_CHANNELS.md §3.2)."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate

    return templates.TemplateResponse(
        request, "channels/parse_step1.html", {"error": None, "form": _CHANNEL_PARSE_FORM_DEFAULTS}
    )


@app.post("/channels/parse", response_class=HTMLResponse)
async def channel_parse_submit(
    request: Request,
    channel_input: str = Form(...),
    post_limit: int = Form(50),
    date_from: str = Form(""),
    date_to: str = Form(""),
    text_only: bool = Form(False),
    skip_forwards: bool = Form(True),
    min_text_length: int = Form(0),
    collect_urls: bool = Form(False),
    collect_commenters: bool = Form(False),
    voice_dna: bool = Form(True),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Валидация формата (F-71) — идёт синхронно, без сети; существование
    канала на t.me проверяется асинхронно внутри run_channel_parse_job
    (статус validating), не здесь."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate
    current_user = await get_current_user(request)

    form_state = {
        "channel_input": channel_input,
        "post_limit": post_limit,
        "date_from": date_from,
        "date_to": date_to,
        "text_only": text_only,
        "skip_forwards": skip_forwards,
        "min_text_length": min_text_length,
        "collect_urls": collect_urls,
        "collect_commenters": collect_commenters,
        "voice_dna": voice_dna,
    }

    username = normalize_channel_username(channel_input)
    if username is None:
        return templates.TemplateResponse(
            request,
            "channels/parse_step1.html",
            {
                "error": "Enter a valid public channel: @channel, t.me/channel, or the full URL.",
                "form": form_state,
            },
        )

    settings = get_settings()
    clamped_limit = min(max(post_limit, 1), settings.channel_parse_max_posts)

    params = {
        "post_limit": clamped_limit,
        "date_from": date_from or None,
        "date_to": date_to or None,
        "text_only": text_only,
        "skip_forwards": skip_forwards,
        "min_text_length": min_text_length,
        "collect_urls": collect_urls,
        "collect_commenters": collect_commenters,
        "voice_dna": voice_dna,
    }

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        job = ChannelParseJob(
            workspace_id=workspace_id,
            requested_by_user_id=current_user.id if current_user else None,
            channel_username=username,
            params_json=params,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

    run_channel_parse_job.delay(job.id)
    return RedirectResponse(f"/channels/parse/{job.id}", status_code=303)


@app.get("/channels/parse/{job_id}", response_class=HTMLResponse)
async def channel_parse_progress_page(
    request: Request, job_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """Шаг 2 — прогресс + мини-игра (TZ_CHANNELS.md §3.3). parse-race.js
    редиректит на шаг 3 (/results) сам, когда status становится done."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        job = await session.get(ChannelParseJob, job_id)
    if job is None or job.workspace_id != workspace_id:
        return HTMLResponse("Job not found", status_code=404)
    return templates.TemplateResponse(request, "channels/parse_step2.html", {"job": job})


CHANNEL_RESULTS_SORT_COLUMNS = {
    "date": ChannelParsedPost.published_at.desc(),
    "views": ChannelParsedPost.views.desc(),
    "reactions": ChannelParsedPost.reactions_total.desc(),
    "comments": ChannelParsedPost.comments_count.desc(),
}


async def _load_channel_job_and_posts(
    workspace_id: int, job_id: int, sort: str
) -> tuple[ChannelParseJob | None, list[ChannelParsedPost]]:
    order = CHANNEL_RESULTS_SORT_COLUMNS.get(sort, CHANNEL_RESULTS_SORT_COLUMNS["date"])
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        job = await session.get(ChannelParseJob, job_id)
        if job is None or job.workspace_id != workspace_id:
            return None, []
        posts = (
            (
                await session.execute(
                    select(ChannelParsedPost)
                    .where(ChannelParsedPost.job_id == job_id)
                    .order_by(order)
                )
            )
            .scalars()
            .all()
        )
    return job, list(posts)


@app.get("/channels/parse/{job_id}/results", response_class=HTMLResponse)
async def channel_parse_results_page(
    request: Request,
    job_id: int,
    sort: str = "date",
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Шаг 3 wizard'а — таблица спарсенных постов (TZ_CHANNELS.md §3.4)."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    job, posts = await _load_channel_job_and_posts(workspace_id, job_id, sort)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    return templates.TemplateResponse(
        request, "channels/parse_step3.html", {"job": job, "posts": posts, "sort": sort}
    )


@app.get("/channels/parse/{job_id}/export/posts.csv")
async def export_channel_posts_csv(
    job_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    _job, posts = await _load_channel_job_and_posts(workspace_id, job_id, "date")
    return _download(channel_posts_to_csv(posts), f"channel-{job_id}-posts.csv", "text/csv")


@app.get("/channels/parse/{job_id}/export/posts.md")
async def export_channel_posts_md(
    job_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    _job, posts = await _load_channel_job_and_posts(workspace_id, job_id, "date")
    return _download(
        channel_posts_to_markdown(posts), f"channel-{job_id}-posts.md", "text/markdown"
    )


async def _load_channel_job_and_report(
    workspace_id: int, job_id: int
) -> tuple[ChannelParseJob | None, ChannelVoiceReport | None]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        job = await session.get(ChannelParseJob, job_id)
        if job is None or job.workspace_id != workspace_id:
            return None, None
        report = (
            await session.execute(
                select(ChannelVoiceReport).where(ChannelVoiceReport.job_id == job_id)
            )
        ).scalar_one_or_none()
    return job, report


@app.get("/channels/parse/{job_id}/report", response_class=HTMLResponse)
async def channel_parse_report_page(
    request: Request, job_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    """Шаг 4 wizard'а — Voice DNA отчёт (TZ_CHANNELS.md §3.5)."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    job, report = await _load_channel_job_and_report(workspace_id, job_id)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)

    report_ready = report is not None and report.status == ChannelVoiceReportStatus.done
    date_range = "—"
    if job.date_range_from and job.date_range_to:
        date_range = f"{job.date_range_from.isoformat()} – {job.date_range_to.isoformat()}"

    return templates.TemplateResponse(
        request,
        "channels/parse_step4_report.html",
        {
            "job": job,
            "report": report,
            "report_ready": report_ready,
            "date_range": date_range,
            "profile": (report.profile_json or {}) if report_ready else {},
            "sections": (report.report_sections_json or {}) if report_ready else {},
            "chart_data": (report.chart_data_json or {}) if report_ready else {},
        },
    )


@app.get("/channels/parse/{job_id}/export/report.md")
async def export_channel_report_md(
    job_id: int, workspace_id: int | None = Depends(get_current_workspace_id)
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    job, report = await _load_channel_job_and_report(workspace_id, job_id)
    if job is None or report is None or not report.report_md:
        return HTMLResponse("Report not available", status_code=404)
    return _download(report.report_md, f"channel-{job_id}-voice-dna-report.md", "text/markdown")


CHANNEL_HISTORY_PAGE_SIZE = 20


@app.get("/channels", response_class=HTMLResponse)
async def channels_history_page(
    request: Request,
    page: int = 1,
    mine: bool = False,
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """История запусков Channel Parser (TZ_CHANNELS.md §9.2) — атрибуция
    "кто запросил" + личная вкладка "Мои каналы" (волна 6, ChannelWatch)."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate
    current_user = await get_current_user(request)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        watched_usernames: set[str] = set()
        if current_user is not None:
            watched_usernames = set(
                (
                    await session.execute(
                        select(ChannelWatch.channel_username).where(
                            ChannelWatch.user_id == current_user.id
                        )
                    )
                )
                .scalars()
                .all()
            )

        conditions = [ChannelParseJob.workspace_id == workspace_id]
        if mine:
            conditions.append(ChannelParseJob.channel_username.in_(watched_usernames))

        total = (
            await session.execute(
                select(func.count()).select_from(ChannelParseJob).where(*conditions)
            )
        ).scalar_one()
        jobs = (
            (
                await session.execute(
                    select(ChannelParseJob)
                    .where(*conditions)
                    .order_by(ChannelParseJob.created_at.desc(), ChannelParseJob.id.desc())
                    .offset((page - 1) * CHANNEL_HISTORY_PAGE_SIZE)
                    .limit(CHANNEL_HISTORY_PAGE_SIZE)
                )
            )
            .scalars()
            .all()
        )

        requester_ids = {job.requested_by_user_id for job in jobs if job.requested_by_user_id}
        requesters: dict[int, str] = {}
        if requester_ids:
            rows = (
                (await session.execute(select(User).where(User.id.in_(requester_ids))))
                .scalars()
                .all()
            )
            requesters = {
                u.id: u.display_name or u.full_name or u.username or str(u.telegram_id)
                for u in rows
            }

    return templates.TemplateResponse(
        request,
        "channels/index.html",
        {
            "jobs": jobs,
            "total": total,
            "page": page,
            "page_size": CHANNEL_HISTORY_PAGE_SIZE,
            "mine": mine,
            "requesters": requesters,
            "watched_usernames": watched_usernames,
            "is_logged_in": current_user is not None,
        },
    )


@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    user = await get_current_user(request)
    if user is None:
        return RedirectResponse("/login")

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
        )
        workspace = await session.get(Workspace, membership.workspace_id) if membership else None
        members = []
        invites = []
        if workspace is not None:
            rows = (
                await session.execute(
                    select(WorkspaceMember, User)
                    .join(User, User.id == WorkspaceMember.user_id)
                    .where(WorkspaceMember.workspace_id == workspace.id)
                )
            ).all()
            members = [
                {
                    "display_name": u.display_name
                    or u.full_name
                    or u.username
                    or str(u.telegram_id),
                    "role": m.role.value,
                }
                for m, u in rows
            ]
            invites = list(
                (
                    await session.execute(
                        select(Invite)
                        .where(Invite.workspace_id == workspace.id)
                        .order_by(Invite.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )

    is_owner = membership is not None and membership.role.value == "owner"
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "account_user": user,
            "workspace": workspace,
            "members": members,
            "invites": invites,
            "is_owner": is_owner,
        },
    )


@app.get("/changelog", response_class=HTMLResponse)
async def changelog_page(request: Request):
    return templates.TemplateResponse(
        request, "changelog.html", {"changelog": CHANGELOG, "current_version": CURRENT_VERSION}
    )


@app.get("/posts", response_class=HTMLResponse)
async def posts_page(
    request: Request,
    tag: str | None = None,
    area: str | None = None,
    sort: str = "priority",
    page: int = 1,
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_posts(
            session, workspace_id=workspace_id, tag=tag, area=area, sort=sort, page=page
        )
        all_tags = await list_all_post_tags(session, workspace_id)

    return templates.TemplateResponse(
        request,
        "posts.html",
        {
            "posts": result.items,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "tag": tag,
            "area": area,
            "sort": sort,
            "all_tags": all_tags,
        },
    )


POST_URL_RE = re.compile(r"^https?://t\.me/([A-Za-z0-9_]{5,32})/(\d+)/?(?:\?.*)?$")


@app.post("/posts/add", response_class=HTMLResponse)
async def add_post_manual(
    request: Request,
    url: str = Form(...),
    workspace_id: int | None = Depends(get_current_workspace_id),
):
    """Ручное добавление поста по публичной t.me-ссылке — фетчим текст со
    страницы предпросмотра Telegram (доступна без авторизации для открытых
    каналов) и дальше идём через тот же worker.posts.process_post, что и
    форварды из бота."""
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate
    current_user = await get_current_user(request)

    match = POST_URL_RE.match(url.strip())
    if match is None:
        status_text = "Enter a public post link like https://t.me/channel/123."
    else:
        channel, message_id_str = match.group(1), match.group(2)
        post_url = f"https://t.me/{channel}/{message_id_str}"
        try:
            meta = await fetch_metadata(post_url)
            post_text = meta.description or None
        except FetchError:
            post_text = None

        chat_id = -int(hashlib.sha256(channel.encode()).hexdigest()[:12], 16)
        payload = {
            "workspace_id": workspace_id,
            "chat_id": chat_id,
            "message_id": int(message_id_str),
            "chat_title": channel,
            "sender_id": current_user.telegram_id if current_user else None,
            "sender_name": None,
            "text": post_text,
            "urls": [],
            "post_url": post_url,
        }
        enqueue_post_processing(payload, countdown=0)
        status_text = "Added — will appear in the table once processed (a few seconds)."

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await query_posts(session, workspace_id=workspace_id, sort="priority", page=1)
        all_tags = await list_all_post_tags(session, workspace_id)

    list_response = templates.TemplateResponse(
        request,
        "_posts_list.html",
        {
            "posts": result.items,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "tag": None,
            "area": None,
            "sort": "priority",
        },
    )
    status_html = (
        f'<p id="add-post-status" hx-swap-oob="true" class="card-meta">'
        f"{html.escape(status_text)}</p>"
    )
    return HTMLResponse(list_response.body.decode() + status_html)


def _download(content: str, filename: str, media_type: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/links.csv")
async def export_links_csv(workspace_id: int | None = Depends(get_current_workspace_id)):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        links = (
            (
                await session.execute(
                    select(Link).where(Link.workspace_id == workspace_id, Link.is_hidden.is_(False))
                )
            )
            .scalars()
            .all()
        )
        for link in links:
            await session.refresh(link, attribute_names=["tags"])
    return _download(links_to_csv(links), "links.csv", "text/csv")


@app.get("/export/links.md")
async def export_links_md(workspace_id: int | None = Depends(get_current_workspace_id)):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        links = (
            (
                await session.execute(
                    select(Link).where(Link.workspace_id == workspace_id, Link.is_hidden.is_(False))
                )
            )
            .scalars()
            .all()
        )
        for link in links:
            await session.refresh(link, attribute_names=["tags"])
    return _download(links_to_markdown(links), "links.md", "text/markdown")


@app.get("/export/posts.csv")
async def export_posts_csv(workspace_id: int | None = Depends(get_current_workspace_id)):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        posts = (
            (
                await session.execute(
                    select(Post).where(Post.workspace_id == workspace_id, Post.is_hidden.is_(False))
                )
            )
            .scalars()
            .all()
        )
        for post in posts:
            await session.refresh(post, attribute_names=["tags"])
    return _download(posts_to_csv(posts), "posts.csv", "text/csv")


@app.get("/export/posts.md")
async def export_posts_md(workspace_id: int | None = Depends(get_current_workspace_id)):
    gate = _require_workspace(workspace_id)
    if isinstance(gate, RedirectResponse):
        return gate
    workspace_id = gate

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        posts = (
            (
                await session.execute(
                    select(Post).where(Post.workspace_id == workspace_id, Post.is_hidden.is_(False))
                )
            )
            .scalars()
            .all()
        )
        for post in posts:
            await session.refresh(post, attribute_names=["tags"])
    return _download(posts_to_markdown(posts), "posts.md", "text/markdown")
