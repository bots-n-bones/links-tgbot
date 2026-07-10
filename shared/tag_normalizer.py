"""Нормализация тегов (TZ F-23) и линия обороны NF-13 против prompt injection:
любой тег, не прошедший allowlist, отбрасывается — теги никогда не содержат
произвольный текст, вернувшийся из LLM."""

import re

_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")
MAX_TAG_LENGTH = 30


def normalize_tag(raw: str, synonyms: dict[str, str] | None = None) -> str | None:
    """Возвращает канонический тег или None, если raw не проходит валидацию.

    synonyms — маппинг {raw_value: canonical_tag} из таблицы tag_synonyms
    (например {"ии": "ai", "дизайн": "design"}).
    """
    if not raw:
        return None

    candidate = raw.strip().lower()
    if synonyms and candidate in synonyms:
        candidate = synonyms[candidate]

    candidate = candidate.strip().lower()[:MAX_TAG_LENGTH]

    if not _TAG_RE.match(candidate):
        return None

    return candidate


def normalize_tags(raw_tags: list[str], synonyms: dict[str, str] | None = None) -> list[str]:
    """Нормализует список тегов, отбрасывает невалидные, убирает дубликаты (порядок сохраняется)."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_tags:
        normalized = normalize_tag(raw, synonyms)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
