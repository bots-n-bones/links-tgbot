"""Channel Parser: query-хелперы + JSON status API (TZ_CHANNELS.md §9)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.models import ChannelParseJob
from db.session import get_sessionmaker

router = APIRouter(prefix="/api/channels", tags=["channels"])


class JobStatusOut(BaseModel):
    status: str
    progress_current: int
    progress_total: int
    progress_pct: float
    error_message: str | None
    posts_count: int
    voice_report_status: str | None = None  # заполняется в волне F


@router.get("/parse/{job_id}/status")
async def job_status(job_id: int) -> JobStatusOut:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        job = await session.get(ChannelParseJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")

    pct = (job.progress_current / job.progress_total * 100) if job.progress_total else 0.0
    return JobStatusOut(
        status=job.status.value,
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        progress_pct=round(min(pct, 100.0), 1),
        error_message=job.error_message,
        posts_count=job.posts_count,
    )
