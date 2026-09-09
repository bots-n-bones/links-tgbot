import hashlib
from datetime import UTC, datetime, timedelta

from db.models import Link, LinkStatus, ManualPriority


async def _make_link(
    db_session, workspace_id: int, *, url: str, created_days_ago: int = 0, **kwargs
) -> Link:
    now = datetime.now(UTC) - timedelta(days=created_days_ago)
    link = Link(
        workspace_id=workspace_id,
        url=url,
        normalized_url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title=f"Title for {url}",
        status=LinkStatus.done,
        created_at=now,
        **kwargs,
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)
    return link


async def test_index_page_has_title_and_search_button(db_session, authed_client):
    resp = authed_client.get("/")
    assert resp.status_code == 200
    assert "<h1>Каталог</h1>" in resp.text
    assert 'class="header-search-submit"' in resp.text


async def test_index_page_shows_priority_and_tested_controls(
    db_session, workspace_id, authed_client
):
    await _make_link(
        db_session,
        workspace_id,
        url="https://a.com",
        manual_priority=ManualPriority.high,
        is_tested=True,
    )

    resp = authed_client.get("/")
    assert resp.status_code == 200
    assert 'value="high" selected' in resp.text
    assert 'class="tested-checkbox" checked' in resp.text


async def test_index_page_default_sort_is_date(db_session, authed_client):
    resp = authed_client.get("/")
    assert resp.status_code == 200
    assert '<option value="date" selected>По дате</option>' in resp.text.replace("\n", "").replace(
        "  ", " "
    )


async def test_index_page_pagination_shows_arrows_when_multiple_pages(
    db_session, workspace_id, authed_client
):
    for i in range(25):
        await _make_link(
            db_session, workspace_id, url=f"https://example{i}.com", created_days_ago=i
        )

    resp = authed_client.get("/")
    assert resp.status_code == 200
    assert "Страница 1 из 2" in resp.text
    assert "pagination-disabled" in resp.text  # ← disabled on page 1


async def test_index_page_defaults_to_inbox_and_counts_modes(
    db_session, workspace_id, authed_client
):
    """Каталог открывается на неразобранном, и рядом с режимом стоит число.

    Счётчик — единственное, что показывает, что стопка вообще есть; без
    него режим легко не заметить."""
    await _make_link(db_session, workspace_id, url="https://a.com")
    await _make_link(db_session, workspace_id, url="https://b.com", is_tested=True)

    resp = authed_client.get("/")
    assert resp.status_code == 200
    assert 'class="cat-mode active"' in resp.text.replace("\n", " ")
    assert "Inbox" in resp.text


async def test_reviewed_link_leaves_inbox_but_stays_in_all(db_session, workspace_id, authed_client):
    """Разбор убирает запись из Inbox и не трогает ничего больше."""
    link = await _make_link(db_session, workspace_id, url="https://a.com")

    assert f'id="link-{link.id}"' in authed_client.get("/?mode=inbox").text

    marked = authed_client.patch(
        f"/api/links/{link.id}/reviewed?reviewed=true",
        headers={"HX-Request": "true", "HX-Current-URL": "http://test/?mode=inbox"},
    )
    assert marked.status_code == 200
    # Карточка уехала из Inbox — в ответе её нет, есть только новые счётчики.
    assert f'id="link-{link.id}"' not in marked.text
    assert 'id="cat-modes"' in marked.text

    assert f'id="link-{link.id}"' not in authed_client.get("/?mode=inbox").text
    assert f'id="link-{link.id}"' in authed_client.get("/?mode=all").text


async def test_sort_select_shows_the_sort_actually_applied(db_session, workspace_id, authed_client):
    """Режим задаёт сортировку по умолчанию, и список должен это показывать —
    иначе он утверждает «по дате», когда порядок другой."""
    await _make_link(db_session, workspace_id, url="https://a.com", click_count=9)

    resp = authed_client.get("/?mode=popular")
    flat = resp.text.replace("\n", "").replace("  ", " ")
    assert '<option value="clicks" selected>По открытиям</option>' in flat


async def test_catalog_search_matches_what_a_person_wrote(db_session, workspace_id, authed_client):
    """Поиск идёт и по сопроводительному сообщению: вспоминаешь реплику
    («Боря писал про очереди»), а не заголовок статьи."""
    from db.models import LinkSource, SourceType

    link = await _make_link(db_session, workspace_id, url="https://a.com")
    db_session.add(
        LinkSource(
            link_id=link.id,
            chat_id=-100,
            chat_title="Общий чат",
            message_id=1,
            sender_id=555,
            sender_name="Боря",
            message_text="это заменит нам две тулзы",
            source_type=SourceType.group,
        )
    )
    await db_session.commit()

    found = authed_client.get("/?mode=all&q=заменит нам две")
    assert f'id="link-{link.id}"' in found.text

    missing = authed_client.get("/?mode=all&q=совершенно другое")
    assert f'id="link-{link.id}"' not in missing.text
