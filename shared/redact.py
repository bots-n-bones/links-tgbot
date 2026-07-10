"""Маскирование токенов в URL перед логированием/сохранением сообщений об ошибках (NF-12)."""

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TOKEN_PARAM_NAMES = {
    "token",
    "access_token",
    "api_key",
    "apikey",
    "key",
    "secret",
    "auth",
    "password",
    "session",
    "session_id",
}


def redact_url_tokens(url: str) -> str:
    """Заменяет значения query-параметров, похожих на токены/ключи, на '***'."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if not pairs:
        return url

    redacted = [(k, "***" if k.lower() in _TOKEN_PARAM_NAMES else v) for k, v in pairs]
    if redacted == pairs:
        return url

    return urlunparse(parsed._replace(query=urlencode(redacted)))


def redact_text(text: str) -> str:
    """Маскирует токены в URL внутри произвольного текста (например, в тексте исключения)."""

    def _replace(match: re.Match) -> str:
        return redact_url_tokens(match.group(0))

    return re.sub(r"https?://\S+", _replace, text)
