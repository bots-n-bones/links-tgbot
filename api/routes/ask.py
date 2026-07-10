"""POST /api/ask (TZ F-80/81/82/83) — RAG Q&A по базе ссылок."""

from fastapi import APIRouter
from pydantic import BaseModel

from worker.rag import answer_question

router = APIRouter(prefix="/api", tags=["ask"])


class AskRequest(BaseModel):
    question: str


class MatchedLinkOut(BaseModel):
    id: int
    url: str
    title: str | None
    description: str | None
    source_count: int
    unique_senders: int


class AskResponse(BaseModel):
    answer: str
    matched_links: list[MatchedLinkOut]


@router.post("/ask", response_model=AskResponse)
async def ask_question(body: AskRequest) -> AskResponse:
    result = await answer_question(body.question)
    return AskResponse(
        answer=result.answer,
        matched_links=[
            MatchedLinkOut(
                id=m.id,
                url=m.url,
                title=m.title,
                description=m.description,
                source_count=m.source_count,
                unique_senders=m.unique_senders,
            )
            for m in result.matched_links
        ],
    )
