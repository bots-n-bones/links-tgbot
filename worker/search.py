"""SearchClient за интерфейсом: OpenAI web search (единственный провайдер,
решение №2 в плане — Tavily/Serper не подключаются) + fake для тестов.

Используется в Фазе 7 (research-отчёты); интерфейс и fake-реализация готовы
уже здесь, реальная OpenAI-реализация будет точечно проверена вручную при
первом реальном research-отчёте (структура ответа Responses API web_search
может потребовать донастройки парсинга)."""

from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI

from shared.config import get_settings


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchClient(Protocol):
    async def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]: ...


class OpenAIWebSearchClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]:
        response = await self._client.responses.create(
            model=self._model,
            tools=[{"type": "web_search"}],
            input=f"Найди материалы по теме: {query}",
        )
        results: list[SearchResult] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "message":
                continue
            for content in getattr(item, "content", []) or []:
                for annotation in getattr(content, "annotations", []) or []:
                    if getattr(annotation, "type", None) == "url_citation":
                        results.append(
                            SearchResult(
                                title=getattr(annotation, "title", None) or annotation.url,
                                url=annotation.url,
                                snippet=(getattr(content, "text", "") or "")[:300],
                            )
                        )

        seen: set[str] = set()
        deduped: list[SearchResult] = []
        for r in results:
            if r.url not in seen:
                seen.add(r.url)
                deduped.append(r)
        return deduped[:max_results]


class FakeSearchClient:
    async def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]:
        count = min(max_results, 8)
        return [
            SearchResult(
                title=f"Фейковый результат {i} по «{query}»",
                url=f"https://example.com/search/{query[:20]}/{i}",
                snippet=f"Фейковый сниппет {i}.",
            )
            for i in range(count)
        ]


def get_search_client() -> SearchClient:
    settings = get_settings()
    if settings.is_test or not settings.openai_api_key:
        return FakeSearchClient()
    return OpenAIWebSearchClient(settings.openai_api_key, settings.openai_model_report)
