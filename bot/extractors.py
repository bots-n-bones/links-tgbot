"""Извлечение URL из Telegram-сообщений (TZ §3.3): entities, regex-фоллбек,
caption, пересланные сообщения. Работает с любым объектом, у которого есть
атрибуты text/caption/entities/caption_entities (aiogram Message или тестовый
дублёр), чтобы не тянуть aiogram в юнит-тесты."""

import re

_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+",
    re.IGNORECASE,
)


def _entities_urls(text: str | None, entities: list | None) -> list[str]:
    if not text or not entities:
        return []
    # Telegram считает offset/length в UTF-16 code units, а не в Python-символах
    # (см. https://core.telegram.org/api/entities#entity-length) — любой
    # astral-символ перед ссылкой (большинство эмодзи: 🗣🎼💥👋...) занимает 2
    # UTF-16-юнита, но 1 Python-символ, и прямой срез text[offset:offset+length]
    # тогда уезжает вперёд, прихватывая хвост (перенос строки и т.п.), из-за
    # чего httpx падает с InvalidURL. Режем по UTF-16-представлению и декодируем
    # обратно — так офсеты совпадают с тем, что имел в виду Telegram.
    text_utf16 = text.encode("utf-16-le")
    urls = []
    for entity in entities:
        entity_type = getattr(entity, "type", None)
        if entity_type == "url":
            offset, length = entity.offset, entity.length
            urls.append(text_utf16[offset * 2 : (offset + length) * 2].decode("utf-16-le"))
        elif entity_type == "text_link":
            url = getattr(entity, "url", None)
            if url:
                urls.append(url)
    return urls


def _regex_urls(text: str | None) -> list[str]:
    if not text:
        return []
    return [m.rstrip(".,;:!?)") for m in _URL_RE.findall(text)]


def extract_urls(message: object) -> list[str]:
    """Возвращает список уникальных URL из сообщения (порядок сохраняется).

    Покрывает: entities (url/text_link) и regex-фоллбек в тексте, то же для
    caption медиа-сообщений. Пересланные сообщения обрабатываются тем же
    путём — Telegram уже кладёт их содержимое в text/caption с сохранением
    entities, отдельной обработки не требуется.
    """
    text = getattr(message, "text", None)
    caption = getattr(message, "caption", None)
    entities = getattr(message, "entities", None)
    caption_entities = getattr(message, "caption_entities", None)

    candidates = [
        *_entities_urls(text, entities),
        *_regex_urls(text),
        *_entities_urls(caption, caption_entities),
        *_regex_urls(caption),
    ]

    seen: set[str] = set()
    result: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result
