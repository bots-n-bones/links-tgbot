import hashlib
from datetime import UTC, datetime, timedelta

from starlette.testclient import TestClient

from api.main import app
from db.models import Link, LinkSource, LinkStatus, LinkTag, SourceType, Tag


async def _make_link(
    db_session,
    *,
    url: str,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    source_count: int = 1,
    unique_senders: int = 1,
    priority_score: float = 1.0,
    is_hidden: bool = False,
    created_days_ago: int = 0,
    chat_title: str | None = None,
) -> Link:
    now = datetime.now(UTC) - timedelta(days=created_days_ago)
    link = Link(
        url=url,
        normalized_url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title=title,
        description=description,
        status=LinkStatus.done,
        source_count=source_count,
        unique_senders=unique_senders,
        priority_score=priority_score,
        is_hidden=is_hidden,
        created_at=now,
    )
    db_session.add(link)
    await db_session.flush()

    for name in tags or []:
        tag_obj = Tag(name=name, slug=name)
        db_session.add(tag_obj)
        await db_session.flush()
        db_session.add(LinkTag(link_id=link.id, tag_id=tag_obj.id))

    db_session.add(
        LinkSource(
            link_id=link.id,
            chat_title=chat_title,
            sender_id=1,
            source_type=SourceType.group,
            created_at=now,
        )
    )
    await db_session.commit()
    await db_session.refresh(link)
    return link


async def test_health_endpoint(db_session):
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_list_links_excludes_hidden(db_session):
    await _make_link(db_session, url="https://a.com", title="A", is_hidden=False)
    await _make_link(db_session, url="https://b.com", title="B", is_hidden=True)

    with TestClient(app) as client:
        resp = client.get("/api/links")
    assert resp.status_code == 200
    urls = {item["url"] for item in resp.json()["items"]}
    assert urls == {"https://a.com"}


async def test_list_links_search_by_title(db_session):
    await _make_link(db_session, url="https://a.com", title="Статья про RAG")
    await _make_link(db_session, url="https://b.com", title="Статья про Docker")

    with TestClient(app) as client:
        resp = client.get("/api/links", params={"q": "RAG"})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://a.com"


async def test_list_links_filter_by_tag(db_session):
    await _make_link(db_session, url="https://a.com", title="A", tags=["ai"])
    await _make_link(db_session, url="https://b.com", title="B", tags=["design"])

    with TestClient(app) as client:
        resp = client.get("/api/links", params={"tag": "ai"})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://a.com"


async def test_list_links_sort_by_count(db_session):
    await _make_link(
        db_session, url="https://few.com", title="Few", source_count=1, priority_score=5.0
    )
    await _make_link(
        db_session, url="https://many.com", title="Many", source_count=9, priority_score=1.0
    )

    with TestClient(app) as client:
        resp = client.get("/api/links", params={"sort": "count"})
    urls = [item["url"] for item in resp.json()["items"]]
    assert urls == ["https://many.com", "https://few.com"]


async def test_list_links_sort_by_priority_default(db_session):
    await _make_link(db_session, url="https://low.com", title="Low", priority_score=1.0)
    await _make_link(db_session, url="https://high.com", title="High", priority_score=9.0)

    with TestClient(app) as client:
        resp = client.get("/api/links")
    urls = [item["url"] for item in resp.json()["items"]]
    assert urls == ["https://high.com", "https://low.com"]


async def test_get_link_detail_includes_sources(db_session):
    link = await _make_link(db_session, url="https://a.com", title="A", chat_title="Общий чат")

    with TestClient(app) as client:
        resp = client.get(f"/api/links/{link.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://a.com"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["chat_title"] == "Общий чат"


async def test_get_link_detail_404(db_session):
    with TestClient(app) as client:
        resp = client.get("/api/links/999999")
    assert resp.status_code == 404


async def test_update_tags_via_form(db_session):
    link = await _make_link(db_session, url="https://a.com", title="A", tags=["old"])

    with TestClient(app) as client:
        resp = client.patch(f"/api/links/{link.id}/tags", data={"tags": "ai, design, <script>"})
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["tags"]) == {"ai", "design"}  # <script> отброшен allowlist'ом


async def test_hide_link_excludes_from_default_list(db_session):
    link = await _make_link(db_session, url="https://a.com", title="A")

    with TestClient(app) as client:
        resp = client.patch(f"/api/links/{link.id}/hide", params={"hidden": "true"})
        assert resp.status_code == 200
        assert resp.json()["is_hidden"] is True

        list_resp = client.get("/api/links")
    urls = {item["url"] for item in list_resp.json()["items"]}
    assert "https://a.com" not in urls


async def test_top_links_excludes_stale_activity(db_session):
    await _make_link(
        db_session, url="https://recent.com", title="Recent", priority_score=5.0, created_days_ago=1
    )
    # выше приоритет, но последний source 30 дней назад — не должна попасть в топ-7д (F-55)
    await _make_link(
        db_session, url="https://old.com", title="Old", priority_score=9.0, created_days_ago=30
    )

    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    top_block = resp.text.split("Сейчас в топе у команды")[1].split("</div>")[0]
    assert "Recent" in top_block
    assert "Old" not in top_block


async def test_index_page_renders(db_session):
    await _make_link(db_session, url="https://a.com", title="Заголовок статьи", tags=["ai"])

    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "Заголовок статьи" in resp.text
    assert "Link Collector" in resp.text


async def test_link_detail_page_renders(db_session):
    link = await _make_link(db_session, url="https://a.com", title="Детальная страница")

    with TestClient(app) as client:
        resp = client.get(f"/links/{link.id}")
    assert resp.status_code == 200
    assert "Детальная страница" in resp.text


async def test_link_detail_page_404(db_session):
    with TestClient(app) as client:
        resp = client.get("/links/999999")
    assert resp.status_code == 404
