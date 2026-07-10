"""Fetch метаданных страницы (TZ F-20/F-21/F-25, retry NF-02)."""

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from shared.redact import redact_text

TEXT_LIMIT = 4000  # F-25: 3000-5000 символов
REQUEST_TIMEOUT = 10.0
MAX_ATTEMPTS = 3  # NF-02


class FetchError(Exception):
    """Fetch исчерпал попытки — вызывающий код переходит на fallback (F-21)."""


@dataclass
class PageMeta:
    title: str | None
    description: str | None
    favicon_url: str | None
    domain: str
    raw_text: str


def _extract_domain(url: str) -> str:
    return urlparse(url).netloc


def _extract_favicon(soup: BeautifulSoup, base_url: str) -> str | None:
    icon = soup.find("link", rel=lambda v: bool(v) and "icon" in v.lower())
    href = icon.get("href") if icon else None
    if href:
        return urljoin(base_url, href)
    return urljoin(base_url, "/favicon.ico")


def _extract_text(soup: BeautifulSoup, limit: int) -> str:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:limit]


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


async def fetch_metadata(url: str, *, text_limit: int = TEXT_LIMIT) -> PageMeta:
    """title/og:description/favicon/domain + текст страницы.

    Raises FetchError после исчерпания retry (403/timeout/paywall и т.п.) —
    вызывающий код (worker/tasks.py) переходит на fallback из контекста
    Telegram-сообщения (F-21).
    """
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "LinkCollectorBot/1.0"}) as client:
            response = await _get(client, url)
    except httpx.HTTPError as exc:
        raise FetchError(redact_text(f"fetch failed for {url}: {exc}")) from exc

    soup = BeautifulSoup(response.text, "html.parser")
    title_tag = soup.find("title")
    og_desc = soup.find("meta", property="og:description") or soup.find(
        "meta", attrs={"name": "description"}
    )
    description = None
    if og_desc is not None:
        content = og_desc.get("content")
        description = content.strip() if content else None

    return PageMeta(
        title=title_tag.get_text(strip=True) if title_tag else None,
        description=description,
        favicon_url=_extract_favicon(soup, str(response.url)),
        domain=_extract_domain(str(response.url)),
        raw_text=_extract_text(soup, text_limit),
    )
