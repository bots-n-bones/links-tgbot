from sqlalchemy import select

import worker.rag as rag_module
from db.models import Link, LinkStatus, QALog
from worker.rag import _strip_hallucinated_urls


class FixedEmbeddingClient:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    async def embed(self, text: str) -> list[float]:
        return self.vector


class FixedLLMClient:
    def __init__(self, canned_answer: str) -> None:
        self.canned_answer = canned_answer
        self.complete_calls: list[dict] = []

    async def complete(self, **kwargs):
        self.complete_calls.append(kwargs)
        return self.canned_answer

    async def describe_link(self, **kwargs):
        raise NotImplementedError


def _dim_vector(hot_index: int, dim: int = 1536) -> list[float]:
    v = [0.0] * dim
    v[hot_index] = 1.0
    return v


async def test_answer_question_ranks_closest_link_first(db_session, monkeypatch):
    close_vec = _dim_vector(0)
    far_vec = _dim_vector(1)  # ортогонален close_vec => дальше по cosine distance

    link_close = Link(
        url="https://close.com",
        normalized_url="close.com",
        url_hash="hash-close",
        title="Близкая ссылка про RAG",
        description="норм. описание",
        status=LinkStatus.done,
        embedding=close_vec,
    )
    link_far = Link(
        url="https://far.com",
        normalized_url="far.com",
        url_hash="hash-far",
        title="Далёкая ссылка",
        description="другое",
        status=LinkStatus.done,
        embedding=far_vec,
    )
    db_session.add_all([link_close, link_far])
    await db_session.commit()

    monkeypatch.setattr(rag_module, "get_embedding_client", lambda: FixedEmbeddingClient(close_vec))
    fake_llm = FixedLLMClient(
        "Ответ со ссылкой https://close.com и выдуманной https://hallucinated.com"
    )
    monkeypatch.setattr(rag_module, "get_llm_client", lambda: fake_llm)

    result = await rag_module.answer_question("что там про RAG?", user_id=42)

    assert result.matched_links[0].url == "https://close.com"
    assert "https://close.com" in result.answer
    assert "https://hallucinated.com" not in result.answer
    assert "[ссылка недоступна]" in result.answer

    logs = (await db_session.execute(select(QALog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].question == "что там про RAG?"
    assert logs[0].user_id == 42
    assert logs[0].matched_link_ids == [link_close.id, link_far.id]


async def test_answer_question_with_empty_db_still_logs(db_session, monkeypatch):
    monkeypatch.setattr(
        rag_module, "get_embedding_client", lambda: FixedEmbeddingClient(_dim_vector(0))
    )
    fake_llm = FixedLLMClient("В базе пока ничего подходящего нет.")
    monkeypatch.setattr(rag_module, "get_llm_client", lambda: fake_llm)

    result = await rag_module.answer_question("есть что-то про X?")

    assert result.matched_links == []
    logs = (await db_session.execute(select(QALog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].matched_link_ids == []


async def test_answer_question_excludes_hidden_links(db_session, monkeypatch):
    hidden_link = Link(
        url="https://hidden.com",
        normalized_url="hidden.com",
        url_hash="hash-hidden",
        title="Скрытая ссылка",
        status=LinkStatus.done,
        embedding=_dim_vector(0),
        is_hidden=True,
    )
    db_session.add(hidden_link)
    await db_session.commit()

    monkeypatch.setattr(
        rag_module, "get_embedding_client", lambda: FixedEmbeddingClient(_dim_vector(0))
    )
    monkeypatch.setattr(rag_module, "get_llm_client", lambda: FixedLLMClient("нет данных"))

    result = await rag_module.answer_question("вопрос")
    assert result.matched_links == []


def test_strip_hallucinated_urls_keeps_allowed_and_masks_others():
    text = "См. https://a.com/x и https://evil.com/y для деталей."
    cleaned = _strip_hallucinated_urls(text, allowed_urls={"https://a.com/x"})
    assert "https://a.com/x" in cleaned
    assert "https://evil.com/y" not in cleaned
    assert "[ссылка недоступна]" in cleaned


def test_strip_hallucinated_urls_no_urls_unchanged():
    text = "Ничего релевантного не нашлось."
    assert _strip_hallucinated_urls(text, allowed_urls=set()) == text
