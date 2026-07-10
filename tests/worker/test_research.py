from sqlalchemy import select

import worker.tasks as tasks_module
from db.models import Link, LinkStatus, ResearchReport
from worker.embeddings import FakeEmbeddingClient
from worker.fetcher import PageMeta
from worker.llm import FakeLLMClient
from worker.search import FakeSearchClient


async def _fake_fetch_ok(url: str) -> PageMeta:
    return PageMeta(title="T", description="D", favicon_url=None, domain="x.com", raw_text="text")


async def test_generate_research_report_creates_and_caches(db_session, monkeypatch):
    link = Link(
        url="https://a.com",
        normalized_url="a.com",
        url_hash="h1",
        title="A",
        description="desc про RAG",
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)

    fake_llm = FakeLLMClient()
    fake_search = FakeSearchClient()
    monkeypatch.setattr(tasks_module, "get_llm_client", lambda: fake_llm)
    monkeypatch.setattr(tasks_module, "get_search_client", lambda: fake_search)

    report_id_1 = await tasks_module._generate_research_report_async(link.id)
    report_id_2 = await tasks_module._generate_research_report_async(link.id)  # F-62: кэш

    assert report_id_1 == report_id_2
    reports = (
        (await db_session.execute(select(ResearchReport).where(ResearchReport.link_id == link.id)))
        .scalars()
        .all()
    )
    assert len(reports) == 1
    assert len(fake_llm.complete_calls) == 1  # LLM вызван только один раз


async def test_add_research_links_bulk_adds_via_dedup_pipeline(db_session, monkeypatch):
    llm = FakeLLMClient()
    monkeypatch.setattr(tasks_module, "get_llm_client", lambda: llm)
    monkeypatch.setattr(tasks_module, "get_embedding_client", lambda: FakeEmbeddingClient())
    monkeypatch.setattr(tasks_module, "fetch_metadata", _fake_fetch_ok)

    source_link = Link(
        url="https://origin.com",
        normalized_url="origin.com",
        url_hash="h-origin",
        title="Origin",
        status=LinkStatus.done,
    )
    db_session.add(source_link)
    await db_session.flush()

    report = ResearchReport(
        link_id=source_link.id,
        topic="тема",
        report_md="отчёт",
        sources_json=[
            {"title": "S1", "url": "https://found1.com", "snippet": "..."},
            {"title": "S2", "url": "https://found2.com", "snippet": "..."},
        ],
        model="gpt-4o",
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    added_ids = await tasks_module._add_research_links_async(report.id)

    assert len(added_ids) == 2
    links = (
        (
            await db_session.execute(
                select(Link).where(Link.url.in_(["https://found1.com", "https://found2.com"]))
            )
        )
        .scalars()
        .all()
    )
    assert len(links) == 2


async def test_add_research_links_empty_sources_returns_empty(db_session):
    source_link = Link(
        url="https://origin2.com",
        normalized_url="origin2.com",
        url_hash="h-origin2",
        status=LinkStatus.done,
    )
    db_session.add(source_link)
    await db_session.flush()
    report = ResearchReport(
        link_id=source_link.id, topic="t", report_md="md", sources_json=[], model="gpt-4o"
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    added_ids = await tasks_module._add_research_links_async(report.id)
    assert added_ids == []
