from datetime import date
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from worker.channel_scraper import (
    ChannelScrapeError,
    normalize_channel_username,
    parse_message_block,
    parse_telegram_count,
    scrape_channel_posts,
    validate_channel,
)

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "tme_s_channel.html"
FIXTURE_HTML = FIXTURE_PATH.read_text()

# Captured before any monkeypatching — the mocked AsyncClient factory below
# needs the real class, not the (monkeypatched) worker.channel_scraper.httpx.AsyncClient,
# which is the *same module object* as this httpx import (patching one patches both,
# so calling httpx.AsyncClient from inside the replacement would recurse into itself).
_RealAsyncClient = httpx.AsyncClient


def _soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE_HTML, "html.parser")


# --- parse_telegram_count ------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("36.3K", 36300),
        ("1.2M", 1200000),
        ("542", 542),
        ("12.4K", 12400),
        (None, None),
        ("", None),
        ("not a number", None),
    ],
)
def test_parse_telegram_count(raw, expected):
    assert parse_telegram_count(raw) == expected


# --- normalize_channel_username ------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://t.me/testchannel", "testchannel"),
        ("t.me/s/testchannel", "testchannel"),
        ("@testchannel", "testchannel"),
        ("testchannel", "testchannel"),
        ("https://t.me/testchannel/123", "testchannel"),
        ("ab", None),  # too short
        ("has spaces", None),
        ("emoji😀name", None),
    ],
)
def test_normalize_channel_username(raw, expected):
    assert normalize_channel_username(raw) == expected


# --- parse_message_block (fixture, offline) ------------------------------


def test_parses_plain_text_post_with_views_and_reactions():
    soup = _soup()
    message = soup.select_one('[data-post="testchannel/100"]')
    post = parse_message_block(message, "testchannel")

    assert post.message_id == 100
    assert post.post_url == "https://t.me/testchannel/100"
    assert "Just shipped a new feature" in post.text
    assert post.views == 12400
    assert post.published_at.isoformat() == "2026-07-01T10:00:00+00:00"
    assert post.is_forward is False
    assert post.has_media is False
    assert post.word_count > 0
    assert post.urls_in_post == ["https://example.com/post-100"]


def test_parses_reactions_with_mixed_emoji_types():
    soup = _soup()
    message = soup.select_one('[data-post="testchannel/100"]')
    post = parse_message_block(message, "testchannel")

    assert len(post.reactions) == 2
    counts = {r["count"] for r in post.reactions}
    assert counts == {1200, 340}
    assert post.reactions_total == 1540


def test_parses_media_only_post_without_views():
    soup = _soup()
    message = soup.select_one('[data-post="testchannel/101"]')
    post = parse_message_block(message, "testchannel")

    assert post.text is None
    assert post.views is None  # F: fallback — нет views span на этом посте
    assert post.has_media is True
    assert post.word_count == 0
    assert post.urls_in_post == []


def test_parses_forwarded_video_post():
    soup = _soup()
    message = soup.select_one('[data-post="testchannel/102"]')
    post = parse_message_block(message, "testchannel")

    assert post.is_forward is True
    assert post.has_media is True
    assert post.views == 3450000


def test_parses_long_text_post_no_media_no_reactions():
    soup = _soup()
    message = soup.select_one('[data-post="testchannel/103"]')
    post = parse_message_block(message, "testchannel")

    assert post.has_media is False
    assert post.reactions == []
    assert post.reactions_total is None
    assert post.word_count > 10


def test_parse_message_block_returns_none_without_data_post():
    soup = BeautifulSoup('<div class="tgme_widget_message">no data-post</div>', "html.parser")
    message = soup.select_one(".tgme_widget_message")
    assert parse_message_block(message, "testchannel") is None


# --- scrape_channel_posts (mocked HTTP, single page from fixture) -------


class _FixtureTransport(httpx.MockTransport):
    """Отдаёт фикстуру на первый запрос, пустую страницу (без .tme_messages_more) дальше."""

    def __init__(self, html: str) -> None:
        self.calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(str(request.url))
            if len(self.calls) == 1:
                return httpx.Response(200, text=html)
            return httpx.Response(200, text='<div class="tgme_channel_history"></div>')

        super().__init__(handler)


async def test_scrape_channel_posts_respects_limit_and_order(monkeypatch):
    transport = _FixtureTransport(FIXTURE_HTML)
    monkeypatch.setattr(
        "worker.channel_scraper.httpx.AsyncClient",
        lambda **kw: _RealAsyncClient(transport=transport),
    )
    monkeypatch.setattr("worker.channel_scraper.asyncio.sleep", _noop_sleep)

    posts = await scrape_channel_posts("testchannel", limit=2, skip_forwards=False)

    assert len(posts) == 2
    # Самые свежие посты собираются первыми (newest-first), т.к. пагинация
    # идёт назад во времени через ?before= — see scrape_channel_posts.
    assert [p.message_id for p in posts] == [103, 102]


async def test_scrape_channel_posts_skips_forwards_by_default(monkeypatch):
    transport = _FixtureTransport(FIXTURE_HTML)
    monkeypatch.setattr(
        "worker.channel_scraper.httpx.AsyncClient",
        lambda **kw: _RealAsyncClient(transport=transport),
    )
    monkeypatch.setattr("worker.channel_scraper.asyncio.sleep", _noop_sleep)

    posts = await scrape_channel_posts("testchannel", limit=10)

    assert 102 not in [p.message_id for p in posts]  # forwarded post


async def test_scrape_channel_posts_date_from_stops_pagination(monkeypatch):
    transport = _FixtureTransport(FIXTURE_HTML)
    monkeypatch.setattr(
        "worker.channel_scraper.httpx.AsyncClient",
        lambda **kw: _RealAsyncClient(transport=transport),
    )
    monkeypatch.setattr("worker.channel_scraper.asyncio.sleep", _noop_sleep)

    posts = await scrape_channel_posts(
        "testchannel", limit=10, date_from=date(2026, 7, 3), skip_forwards=False
    )

    assert all(p.published_at.date() >= date(2026, 7, 3) for p in posts)
    assert 100 not in [p.message_id for p in posts]


async def test_scrape_channel_posts_reports_progress(monkeypatch):
    transport = _FixtureTransport(FIXTURE_HTML)
    monkeypatch.setattr(
        "worker.channel_scraper.httpx.AsyncClient",
        lambda **kw: _RealAsyncClient(transport=transport),
    )
    monkeypatch.setattr("worker.channel_scraper.asyncio.sleep", _noop_sleep)

    progress_calls = []
    await scrape_channel_posts(
        "testchannel", limit=3, skip_forwards=False, on_progress=lambda cur, tot: progress_calls.append((cur, tot))
    )

    assert progress_calls
    assert progress_calls[-1][1] == 3


async def _noop_sleep(*args, **kwargs) -> None:
    return None


# --- validate_channel (mocked HTTP) --------------------------------------


async def test_validate_channel_parses_preview(monkeypatch):
    header_html = """
    <div class="tgme_channel_history"></div>
    <div class="tgme_channel_info_header_title"><span>Test Channel</span></div>
    <i class="tgme_page_photo_image"><img src="https://cdn.example.com/avatar.jpg"></i>
    <div class="tgme_channel_info_counter">
      <span class="counter_value">11.7M</span> <span class="counter_type">subscribers</span>
    </div>
    """
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=header_html))
    monkeypatch.setattr(
        "worker.channel_scraper.httpx.AsyncClient",
        lambda **kw: _RealAsyncClient(transport=transport),
    )

    preview = await validate_channel("testchannel")

    assert preview.username == "testchannel"
    assert preview.title == "Test Channel"
    assert preview.avatar_url == "https://cdn.example.com/avatar.jpg"
    assert preview.subscribers == 11700000


async def test_validate_channel_raises_on_404(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    monkeypatch.setattr(
        "worker.channel_scraper.httpx.AsyncClient",
        lambda **kw: _RealAsyncClient(transport=transport),
    )

    with pytest.raises(ChannelScrapeError):
        await validate_channel("doesnotexist")


async def test_validate_channel_raises_when_history_missing(monkeypatch):
    """Страница отдаёт 200, но без .tgme_channel_history — приватный канал."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html><body>private</body></html>"))
    monkeypatch.setattr(
        "worker.channel_scraper.httpx.AsyncClient",
        lambda **kw: _RealAsyncClient(transport=transport),
    )

    with pytest.raises(ChannelScrapeError):
        await validate_channel("privatechannel")
