"""Канонизация URL для дедупликации ссылок (TZ F-10/F-11)."""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "igshid"}
_TELEGRAM_DOMAINS = {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return lowered in _TRACKING_PARAMS or any(lowered.startswith(p) for p in _TRACKING_PREFIXES)


def normalize_url(raw: str) -> str:
    """Приводит URL к канонической форме для сравнения/хеширования.

    Правила: lowercase схемы и хоста, срез default-портов, удаление
    tracking-параметров (utm_*, fbclid и т.п.), сортировка оставшихся
    query-параметров, срез trailing slash и fragment.
    """
    raw = raw.strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")

    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[: -len(":80")]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[: -len(":443")]

    path = parsed.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    ]
    query_pairs.sort()
    query = urlencode(query_pairs)

    return urlunparse((scheme, netloc, path, "", query, ""))


def url_hash(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


def is_telegram_link(raw: str) -> bool:
    """t.me/telegram.me — ссылки на телеграм-каналы/чаты, а не на контент.
    Обычно попадают в пересланные посты как подпись/атрибуция автора."""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = parsed.netloc.lower().split(":")[0]
    return host in _TELEGRAM_DOMAINS
