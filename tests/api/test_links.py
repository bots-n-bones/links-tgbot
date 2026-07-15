import hashlib
from datetime import UTC, datetime, timedelta

from starlette.testclient import TestClient

from api.main import app
from db.models import Link, LinkSource, LinkStatus, LinkTag, ManualPriority, SourceType, Tag


async def _make_link(
    db_session,
    workspace_id: int,
    *,
    url: str,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    source_count: int = 1,
    unique_senders: int = 1,
    priority_score: float = 1.0,
    manual_priority: ManualPriority = ManualPriority.normal,
    is_hidden: bool = False,
    created_days_ago: int = 0,
    chat_title: str | None = None,
) -> Link:
    now = datetime.now(UTC) - timedelta(days=created_days_ago)
    link = Link(
        workspace_id=workspace_id,
        url=url,
        normalized_url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title=title,
        description=description,
        status=LinkStatus.done,
        source_count=source_count,
        unique_senders=unique_senders,
        priority_score=priority_score,
        manual_priority=manual_priority,
        is_hidden=is_hidden,
        created_at=now,
    )
    db_session.add(link)
    await db_session.flush()

    for name in tags or []:
        tag_obj = Tag(workspace_id=workspace_id, name=name, slug=name)
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


async def test_list_links_excludes_hidden(db_session, workspace_id, authed_client):
    await _make_link(db_session, workspace_id, url="https://a.com", title="A", is_hidden=False)
    await _make_link(db_session, workspace_id, url="https://b.com", title="B", is_hidden=True)

    resp = authed_client.get("/api/links")
    assert resp.status_code == 200
    urls = {item["url"] for item in resp.json()["items"]}
    assert urls == {"https://a.com"}


async def test_list_links_search_by_title(db_session, workspace_id, authed_client):
    await _make_link(db_session, workspace_id, url="https://a.com", title="Статья про RAG")
    await _make_link(db_session, workspace_id, url="https://b.com", title="Статья про Docker")

    resp = authed_client.get("/api/links", params={"q": "RAG"})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://a.com"


async def test_list_links_filter_by_tag(db_session, workspace_id, authed_client):
    await _make_link(db_session, workspace_id, url="https://a.com", title="A", tags=["ai"])
    await _make_link(db_session, workspace_id, url="https://b.com", title="B", tags=["design"])

    resp = authed_client.get("/api/links", params={"tag": "ai"})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://a.com"


async def test_list_links_sort_by_count(db_session, workspace_id, authed_client):
    await _make_link(
        db_session,
        workspace_id,
        url="https://few.com",
        title="Few",
        source_count=1,
        priority_score=5.0,
    )
    await _make_link(
        db_session,
        workspace_id,
        url="https://many.com",
        title="Many",
        source_count=9,
        priority_score=1.0,
    )

    resp = authed_client.get("/api/links", params={"sort": "count"})
    urls = [item["url"] for item in resp.json()["items"]]
    assert urls == ["https://many.com", "https://few.com"]


async def test_list_links_sort_by_priority_uses_manual_priority(
    db_session, workspace_id, authed_client
):
    await _make_link(
        db_session,
        workspace_id,
        url="https://low.com",
        title="Low",
        manual_priority=ManualPriority.low,
    )
    await _make_link(
        db_session,
        workspace_id,
        url="https://high.com",
        title="High",
        manual_priority=ManualPriority.high,
    )

    resp = authed_client.get("/api/links", params={"sort": "priority"})
    urls = [item["url"] for item in resp.json()["items"]]
    assert urls == ["https://high.com", "https://low.com"]


async def test_list_links_default_sort_is_date(db_session, workspace_id, authed_client):
    await _make_link(
        db_session, workspace_id, url="https://old.com", title="Old", created_days_ago=5
    )
    await _make_link(
        db_session, workspace_id, url="https://new.com", title="New", created_days_ago=0
    )

    resp = authed_client.get("/api/links")
    urls = [item["url"] for item in resp.json()["items"]]
    assert urls == ["https://new.com", "https://old.com"]


async def test_get_link_detail_includes_sources(db_session, workspace_id, authed_client):
    link = await _make_link(
        db_session, workspace_id, url="https://a.com", title="A", chat_title="Общий чат"
    )

    resp = authed_client.get(f"/api/links/{link.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://a.com"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["chat_title"] == "Общий чат"


async def test_get_link_detail_404(db_session, authed_client):
    resp = authed_client.get("/api/links/999999")
    assert resp.status_code == 404


async def test_update_link_via_form(db_session, workspace_id, authed_client):
    link = await _make_link(db_session, workspace_id, url="https://a.com", title="A", tags=["old"])

    resp = authed_client.patch(
        f"/api/links/{link.id}",
        data={
            "title": "Новый заголовок",
            "description": "Новое описание",
            "tags": "ai, design, <script>",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Новый заголовок"
    assert data["description"] == "Новое описание"
    assert set(data["tags"]) == {"ai", "design"}  # <script> отброшен allowlist'ом


async def test_update_link_clears_title_and_description_when_blank(
    db_session, workspace_id, authed_client
):
    link = await _make_link(
        db_session, workspace_id, url="https://a.com", title="A", description="desc"
    )

    resp = authed_client.patch(
        f"/api/links/{link.id}", data={"title": "", "description": "", "tags": ""}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] is None
    assert data["description"] is None
    assert data["tags"] == []


async def test_update_link_sets_manual_priority_and_tested(db_session, workspace_id, authed_client):
    link = await _make_link(db_session, workspace_id, url="https://a.com", title="A")

    resp = authed_client.patch(f"/api/links/{link.id}", data={"priority": "high", "tested": "on"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["manual_priority"] == "high"
    assert data["is_tested"] is True


async def test_update_link_unchecked_checkbox_sets_tested_false(
    db_session, workspace_id, authed_client
):
    link = await _make_link(db_session, workspace_id, url="https://a.com", title="A")
    link.is_tested = True
    await db_session.commit()

    resp = authed_client.patch(f"/api/links/{link.id}", data={})
    assert resp.status_code == 200
    assert resp.json()["is_tested"] is False


async def test_inline_update_priority_only_touches_priority(
    db_session, workspace_id, authed_client
):
    link = await _make_link(
        db_session, workspace_id, url="https://a.com", title="A", description="desc", tags=["kept"]
    )

    resp = authed_client.patch(f"/api/links/{link.id}/priority", data={"priority": "high"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["manual_priority"] == "high"
    assert data["title"] == "A"  # не затронуто
    assert data["description"] == "desc"  # не затронуто
    assert data["tags"] == ["kept"]  # не затронуто


async def test_inline_update_priority_rejects_invalid_value(
    db_session, workspace_id, authed_client
):
    link = await _make_link(db_session, workspace_id, url="https://a.com", title="A")

    resp = authed_client.patch(f"/api/links/{link.id}/priority", data={"priority": "urgent"})
    assert resp.status_code == 422


async def test_inline_update_tested_checked(db_session, workspace_id, authed_client):
    link = await _make_link(db_session, workspace_id, url="https://a.com", title="A")

    resp = authed_client.patch(f"/api/links/{link.id}/tested", data={"tested": "on"})
    assert resp.status_code == 200
    assert resp.json()["is_tested"] is True


async def test_inline_update_tested_unchecked(db_session, workspace_id, authed_client):
    link = await _make_link(db_session, workspace_id, url="https://a.com", title="A")
    link.is_tested = True
    await db_session.commit()

    resp = authed_client.patch(f"/api/links/{link.id}/tested", data={})
    assert resp.status_code == 200
    assert resp.json()["is_tested"] is False


async def test_list_links_sort_by_usefulness_descending(db_session, workspace_id, authed_client):
    low = await _make_link(db_session, workspace_id, url="https://low.com", title="Low")
    high = await _make_link(db_session, workspace_id, url="https://high.com", title="High")
    no_score = await _make_link(db_session, workspace_id, url="https://none.com", title="None")
    low.usefulness_score = 2.0
    high.usefulness_score = 9.0
    no_score.usefulness_score = None
    await db_session.commit()

    resp = authed_client.get("/api/links", params={"sort": "usefulness"})
    urls = [item["url"] for item in resp.json()["items"]]
    assert urls == ["https://high.com", "https://low.com", "https://none.com"]


async def test_hide_link_excludes_from_default_list(db_session, workspace_id, authed_client):
    link = await _make_link(db_session, workspace_id, url="https://a.com", title="A")

    resp = authed_client.patch(f"/api/links/{link.id}/hide", params={"hidden": "true"})
    assert resp.status_code == 200
    assert resp.json()["is_hidden"] is True

    list_resp = authed_client.get("/api/links")
    urls = {item["url"] for item in list_resp.json()["items"]}
    assert "https://a.com" not in urls


async def test_index_page_has_no_old_top_block(db_session, authed_client):
    resp = authed_client.get("/")
    assert resp.status_code == 200
    assert "Сейчас в топе у команды" not in resp.text


async def test_daily_digest_page_lists_digest(db_session, workspace_id, authed_client):
    from db.models import Collection

    collection = Collection(
        workspace_id=workspace_id,
        title="Daily digest — Jul 11, 2026",
        theme="daily-digest",
        summary_md="",
        articles=[{"title": "Great find", "url": "https://a.com", "description": "why"}],
    )
    db_session.add(collection)
    await db_session.commit()
    await db_session.refresh(collection)

    resp = authed_client.get("/digest")
    assert resp.status_code == 200
    assert "1 article" in resp.text

    detail = authed_client.get(f"/digest/{collection.id}")
    assert detail.status_code == 200
    assert "Great find" in detail.text
    assert '<a href="https://a.com"' in detail.text


async def test_index_page_renders(db_session, workspace_id, authed_client):
    await _make_link(
        db_session, workspace_id, url="https://a.com", title="Заголовок статьи", tags=["ai"]
    )

    resp = authed_client.get("/")
    assert resp.status_code == 200
    assert "Заголовок статьи" in resp.text
    assert "NOVA-260" in resp.text


async def test_link_detail_page_renders(db_session, workspace_id, authed_client):
    link = await _make_link(
        db_session, workspace_id, url="https://a.com", title="Детальная страница"
    )

    resp = authed_client.get(f"/links/{link.id}")
    assert resp.status_code == 200
    assert "Детальная страница" in resp.text


async def test_link_detail_page_404(db_session, authed_client):
    resp = authed_client.get("/links/999999")
    assert resp.status_code == 404


async def test_visit_link_increments_click_count_and_redirects(
    db_session, workspace_id, authed_client
):
    link = await _make_link(db_session, workspace_id, url="https://example.com/article")

    authed_client.follow_redirects = False
    resp = authed_client.get(f"/links/{link.id}/visit")
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com/article"

    detail = authed_client.get(f"/api/links/{link.id}")
    assert detail.json()["click_count"] == 1


async def test_visit_link_404_for_missing_link(db_session, authed_client):
    resp = authed_client.get("/links/999999/visit")
    assert resp.status_code == 404


async def test_popular_badge_shown_after_enough_clicks(db_session, workspace_id, authed_client):
    link = await _make_link(db_session, workspace_id, url="https://a.com", title="A")

    authed_client.follow_redirects = False
    for _ in range(3):
        authed_client.get(f"/links/{link.id}/visit")
    resp = authed_client.get("/")
    assert "Popular" in resp.text


async def test_edit_form_and_save_flow(db_session, workspace_id, authed_client):
    link = await _make_link(
        db_session, workspace_id, url="https://a.com", title="Старый заголовок", tags=["old"]
    )

    edit_form = authed_client.get(f"/links/{link.id}/edit-form", headers={"HX-Request": "true"})
    assert edit_form.status_code == 200
    assert "Старый заголовок" in edit_form.text

    saved = authed_client.patch(
        f"/api/links/{link.id}",
        data={"title": "Новый заголовок", "description": "", "tags": "ai"},
        headers={"HX-Request": "true"},
    )
    assert saved.status_code == 200
    assert "Новый заголовок" in saved.text
    assert "Edit" in saved.text  # вернулись в режим просмотра (карточка)


async def test_detail_edit_form_uses_detail_view_on_save(db_session, workspace_id, authed_client):
    link = await _make_link(db_session, workspace_id, url="https://a.com", title="A")

    resp = authed_client.patch(
        f"/api/links/{link.id}",
        data={"title": "Обновлено", "description": "", "tags": "", "view": "detail"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "<h1>Обновлено</h1>" in resp.text
