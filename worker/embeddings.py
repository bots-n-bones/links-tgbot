"""EmbeddingClient за интерфейсом: OpenAI-реализация + детерминированный fake для тестов."""

import hashlib
import random
from typing import Protocol

from openai import AsyncOpenAI

from shared.config import get_settings

EMBEDDING_DIM = 1536


class EmbeddingClient(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class OpenAIEmbeddingClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(model=self._model, input=text[:8000] or " ")
        return list(response.data[0].embedding)


class FakeEmbeddingClient:
    """Детерминированный псевдослучайный вектор из хеша входа — та же строка
    всегда даёт тот же вектор, что удобно для тестов RAG-поиска (Фаза 6)."""

    async def embed(self, text: str) -> list[float]:
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        return [rng.uniform(-1, 1) for _ in range(EMBEDDING_DIM)]


def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()
    if settings.is_test or not settings.openai_api_key:
        return FakeEmbeddingClient()
    return OpenAIEmbeddingClient(settings.openai_api_key, settings.openai_embedding_model)
