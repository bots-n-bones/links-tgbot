"""Скрейпер публичных Telegram-каналов через https://t.me/s/{username} — без
Bot API/userbot (TZ_CHANNELS.md §5). Тот же httpx+tenacity retry-паттерн, что
в worker/fetcher.py.

Селекторы верифицированы вручную в живом браузере против t.me/s/durov и
t.me/s/tass_agency (2026-07-12). Единственное исключение —
.tgme_widget_message_forwarded_from (детекция репостов): ни на одном из
проверенных каналов форвард не встретился, класс взят из TZ_CHANNELS.md §5.2
как есть. Если реальная разметка форвардов отличается, is_forward просто
останется False (soft-fail, не падение job'а) — см. риски §18 TZ."""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

import httpx
from bs4 import BeautifulSoup, Tag
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from shared.config import get_settings
from shared.redact import redact_text

REQUEST_TIMEOUT = 10.0
MAX_ATTEMPTS = 3
EMPTY_PAGE_STOP_LIMIT = 3  # F: 3 пустые страницы подряд -> стоп (TZ §5.2)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
_HEADERS = {"User-Agent": "Nova260ChannelParser/1.0"}

_MEDIA_SELECTOR = ", ".join(
    f".tgme_widget_message_{kind}_wrap"
    for kind in ["photo", "video", "sticker", "roundvideo", "voice", "document"]
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+")


class ChannelScrapeError(Exception):
    """Канал не найден/приватный/недоступен после retry (TZ §5, F-71)."""


@dataclass
class ChannelPreview:
    username: str
    title: str | None
    avatar_url: str | None
    subscribers: int | None


@dataclass
class ScrapedPost:
    message_id: int
    post_url: str
    text: str | None
    published_at: datetime | None
    views: int | None
    reactions: list[dict] = field(default_factory=list)
    reactions_total: int | None = None
    comments_count: int | None = None  # редко доступно с t.me/s/, см. TZ §5.4
    is_forward: bool = False
    has_media: bool = False
    word_count: int = 0
    urls_in_post: list[str] = field(default_factory=list)


def normalize_channel_username(raw: str) -> str | None:
    """'https://t.me/channel', '@channel', 't.me/s/channel' -> 'channel', или
    None если формат не проходит regex `[A-Za-z0-9_]{5,32}` (TZ §3.2 F-71)."""
    value = raw.strip()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^t\.me/(s/)?", "", value)
    value = value.lstrip("@").split("/")[0].split("?")[0]
    return value if USERNAME_RE.match(value) else None


def parse_telegram_count(raw: str | None) -> int | None:
    """'36.3K' -> 36300, '1.2M' -> 1200000, '542' -> 542 (TZ §5.3)."""
    if not raw:
        return None
    cleaned = raw.strip().replace(",", "")
    match = re.match(r"^([\d.]+)\s*([KM]?)$", cleaned, re.IGNORECASE)
    if not match:
        return None
    number, suffix = match.groups()
    try:
        value = float(number)
    except ValueError:
        return None
    if suffix.upper() == "K":
        value *= 1_000
    elif suffix.upper() == "M":
        value *= 1_000_000
    return int(value)


def _extract_urls(text: str) -> list[str]:
    return [m.rstrip(".,;:!?)") for m in _URL_RE.findall(text)]


@retry(
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    response = await client.get(url, timeout=REQUEST_TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    return response


def _parse_reactions(message: Tag) -> tuple[list[dict], int | None]:
    container = message.select_one(".tgme_widget_message_reactions")
    if container is None:
        return [], None
    reactions = []
    for span in container.select(".tgme_reaction"):
        text = span.get_text(strip=True)
        count_match = re.search(r"([\d.]+[KM]?)$", text)
        count = parse_telegram_count(count_match.group(1)) if count_match else None
        emoji_tag = span.select_one("b")
        emoji = emoji_tag.get_text(strip=True) if emoji_tag else None
        reactions.append({"emoji": emoji, "count": count})
    counted = [r["count"] for r in reactions if r["count"] is not None]
    return reactions, (sum(counted) if counted else None)


def parse_message_block(message: Tag, username: str) -> ScrapedPost | None:
    """Парсит один .tgme_widget_message блок. None если это не сообщение
    (например, разметка изменилась и data-post отсутствует)."""
    data_post = message.get("data-post")
    if not data_post or "/" not in data_post:
        return None
    _, _, message_id_str = data_post.rpartition("/")
    if not message_id_str.isdigit():
        return None
    message_id = int(message_id_str)

    text_el = message.select_one(".tgme_widget_message_text")
    text = text_el.get_text(separator="\n", strip=True) if text_el else None

    time_el = message.select_one("time[datetime]")
    published_at = None
    if time_el and time_el.get("datetime"):
        try:
            published_at = datetime.fromisoformat(time_el["datetime"])
        except ValueError:
            published_at = None

    views_el = message.select_one(".tgme_widget_message_views")
    views = parse_telegram_count(views_el.get_text(strip=True)) if views_el else None

    reactions, reactions_total = _parse_reactions(message)
    is_forward = message.select_one(".tgme_widget_message_forwarded_from") is not None
    has_media = message.select_one(_MEDIA_SELECTOR) is not None

    return ScrapedPost(
        message_id=message_id,
        post_url=f"https://t.me/{username}/{message_id}",
        text=text,
        published_at=published_at,
        views=views,
        reactions=reactions,
        reactions_total=reactions_total,
        is_forward=is_forward,
        has_media=has_media,
        word_count=len(text.split()) if text else 0,
        urls_in_post=_extract_urls(text) if text else [],
    )


async def validate_channel(username: str) -> ChannelPreview:
    """GET t.me/s/{username}, парсинг title/avatar/подписчиков (TZ §3.2 F-71).
    Raises ChannelScrapeError на 404/приватный канал/сетевую ошибку после retry."""
    async with httpx.AsyncClient(headers=_HEADERS) as client:
        try:
            response = await _get(client, f"https://t.me/s/{username}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ChannelScrapeError(f"Channel @{username} not found or private") from exc
            raise ChannelScrapeError(
                redact_text(f"validate failed for @{username}: {exc}")
            ) from exc
        except httpx.HTTPError as exc:
            raise ChannelScrapeError(redact_text(f"validate failed for @{username}: {exc}")) from exc

    soup = BeautifulSoup(response.text, "html.parser")
    if soup.select_one(".tgme_channel_history") is None:
        raise ChannelScrapeError(f"Channel @{username} not found or private")

    title_el = soup.select_one(".tgme_channel_info_header_title")
    title = title_el.get_text(strip=True) if title_el else None

    avatar_el = soup.select_one(".tgme_page_photo_image img")
    avatar_url = avatar_el.get("src") if avatar_el else None

    subscribers = None
    for counter in soup.select(".tgme_channel_info_counter"):
        counter_type = counter.select_one(".counter_type")
        if counter_type and "subscriber" in counter_type.get_text(strip=True).lower():
            value_el = counter.select_one(".counter_value")
            if value_el:
                subscribers = parse_telegram_count(value_el.get_text(strip=True))
            break

    return ChannelPreview(
        username=username, title=title, avatar_url=avatar_url, subscribers=subscribers
    )


async def scrape_channel_posts(
    username: str,
    *,
    limit: int,
    date_from: date | None = None,
    date_to: date | None = None,
    skip_forwards: bool = True,
    min_text_length: int = 0,
    text_only: bool = False,
    on_progress: Callable[[int, int], object] | None = None,
) -> list[ScrapedPost]:
    """Пагинация через ?before={message_id} (TZ §5.2). Останов: достигнут
    limit ИЛИ дата < date_from ИЛИ 3 пустые страницы подряд ИЛИ пагинация не
    двигается (защита от зацикливания при неожиданной разметке)."""
    settings = get_settings()
    collected: list[ScrapedPost] = []
    before: int | None = None
    empty_pages = 0

    async with httpx.AsyncClient(headers=_HEADERS) as client:
        while len(collected) < limit:
            url = f"https://t.me/s/{username}"
            if before is not None:
                url += f"?before={before}"

            try:
                response = await _get(client, url)
            except httpx.HTTPError:
                break  # исчерпали retry — отдаём то, что уже собрано

            soup = BeautifulSoup(response.text, "html.parser")
            messages = soup.select(".tgme_widget_message")

            page_posts: list[ScrapedPost] = []
            hit_date_floor = False
            for message in reversed(messages):  # на странице новые внизу
                post = parse_message_block(message, username)
                if post is None:
                    continue
                if date_from and post.published_at and post.published_at.date() < date_from:
                    hit_date_floor = True
                    continue
                if skip_forwards and post.is_forward:
                    continue
                if text_only and not post.text:
                    continue
                if min_text_length and (not post.text or len(post.text) < min_text_length):
                    continue
                if date_to and post.published_at and post.published_at.date() > date_to:
                    continue
                page_posts.append(post)

            if page_posts:
                empty_pages = 0
                collected.extend(page_posts)
                if on_progress:
                    result = on_progress(min(len(collected), limit), limit)
                    if asyncio.iscoroutine(result):
                        await result
            else:
                empty_pages += 1
                if empty_pages >= EMPTY_PAGE_STOP_LIMIT:
                    break

            if hit_date_floor:
                break

            more_link = soup.select_one(".tme_messages_more")
            before_attr = more_link.get("data-before") if more_link else None
            if not before_attr or not before_attr.isdigit():
                break
            next_before = int(before_attr)
            if before is not None and next_before >= before:
                break  # пагинация не двигается — не зацикливаемся
            before = next_before

            await asyncio.sleep(settings.channel_scrape_delay_sec)

    return collected[:limit]
