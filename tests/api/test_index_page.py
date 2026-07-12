import hashlib
from datetime import UTC, datetime, timedelta

from starlette.testclient import TestClient

from api.main import app
from db.models import Link, LinkStatus, ManualPriority


async def _make_link(db_session, *, url: str, created_days_ago: int = 0, **kwargs) -> Link:
    now = datetime.now(UTC) - timedelta(days=created_days_ago)
    link = Link(
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


async def test_index_page_has_title_and_search_button(db_session):
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "<h1>Links</h1>" in resp.text
    assert 'class="header-search-submit"' in resp.text


async def test_index_page_shows_priority_and_tested_columns(db_session):
    await _make_link(
        db_session,
        url="https://a.com",
        manual_priority=ManualPriority.high,
        is_tested=True,
    )

    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "High" in resp.text
    assert "✓ Tested" in resp.text


async def test_index_page_default_sort_is_date(db_session):
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert '<option value="date" selected>By date</option>' in resp.text.replace(
        "\n", ""
    ).replace("  ", " ")


async def test_index_page_pagination_shows_arrows_when_multiple_pages(db_session):
    for i in range(25):
        await _make_link(db_session, url=f"https://example{i}.com", created_days_ago=i)

    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "Page 1 of 2" in resp.text
    assert "pagination-disabled" in resp.text  # ← disabled on page 1
