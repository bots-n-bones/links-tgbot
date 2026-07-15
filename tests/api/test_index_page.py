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
    assert "<h1>Links</h1>" in resp.text
    assert 'class="header-search-submit"' in resp.text


async def test_index_page_shows_priority_and_tested_columns(
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
    assert '<option value="date" selected>By date</option>' in resp.text.replace("\n", "").replace(
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
    assert "Page 1 of 2" in resp.text
    assert "pagination-disabled" in resp.text  # ← disabled on page 1
