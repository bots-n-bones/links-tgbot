"""TZ §4.7, F-60..F-65 — research-отчёты ("Собрать ещё"), JSON-контракт (§8)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from db.models import Link, ResearchReport
from db.session import get_sessionmaker
from worker.tasks import add_research_links, generate_research_report

router = APIRouter(tags=["research"])


class ResearchTriggerResponse(BaseModel):
    status: str  # "pending" | "done"
    research_id: int | None = None


@router.post("/api/links/{link_id}/research", status_code=202)
async def trigger_research(link_id: int) -> ResearchTriggerResponse:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        link = await session.get(Link, link_id)
        if link is None:
            raise HTTPException(404, "Link not found")

        existing = await session.scalar(
            select(ResearchReport)
            .where(ResearchReport.link_id == link_id)
            .order_by(ResearchReport.created_at.desc())
        )
    if existing is not None:
        return ResearchTriggerResponse(status="done", research_id=existing.id)  # F-62: кэш

    generate_research_report.delay(link_id)
    return ResearchTriggerResponse(status="pending")


class ResearchReportOut(BaseModel):
    id: int
    link_id: int
    topic: str | None
    report_md: str
    sources: list[dict]
    model: str | None


@router.get("/api/research/{research_id}")
async def get_research(research_id: int) -> ResearchReportOut:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        report = await session.get(ResearchReport, research_id)
    if report is None:
        raise HTTPException(404, "Research report not found")
    return ResearchReportOut(
        id=report.id,
        link_id=report.link_id,
        topic=report.topic,
        report_md=report.report_md,
        sources=report.sources_json or [],
        model=report.model,
    )


@router.post("/api/research/{research_id}/add-links", status_code=202)
async def add_links_from_research(research_id: int) -> dict:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        report = await session.get(ResearchReport, research_id)
    if report is None:
        raise HTTPException(404, "Research report not found")
    add_research_links.delay(research_id)  # F-65
    return {"status": "queued"}
