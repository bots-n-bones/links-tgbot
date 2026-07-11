"""GET /api/collections (TZ §8, F-74) — тематические подборки."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from db.models import Collection
from db.session import get_sessionmaker

router = APIRouter(prefix="/api/collections", tags=["collections"])


class DigestArticleOut(BaseModel):
    title: str
    url: str
    description: str = ""


class CollectionOut(BaseModel):
    id: int
    title: str
    theme: str | None
    period_start: str | None
    period_end: str | None
    summary_md: str
    link_ids: list[int]
    articles: list[DigestArticleOut]


def _to_out(c: Collection) -> CollectionOut:
    return CollectionOut(
        id=c.id,
        title=c.title,
        theme=c.theme,
        period_start=c.period_start.isoformat() if c.period_start else None,
        period_end=c.period_end.isoformat() if c.period_end else None,
        summary_md=c.summary_md,
        link_ids=c.link_ids or [],
        articles=c.articles or [],
    )


@router.get("")
async def list_collections() -> list[CollectionOut]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        rows = (
            (await session.execute(select(Collection).order_by(Collection.created_at.desc())))
            .scalars()
            .all()
        )
    return [_to_out(c) for c in rows]


@router.get("/{collection_id}")
async def get_collection(collection_id: int) -> CollectionOut:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        collection = await session.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(404, "Collection not found")
    return _to_out(collection)
