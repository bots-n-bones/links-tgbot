"""Форматирование Telegram-ответов со ссылками. Отправляется с parse_mode
HTML, поэтому весь заголовок/текст экранируется html.escape — доверенная
разметка (<a href=...>) добавляется только вокруг него, никогда вокруг
непроверенного контента напрямую."""

import html
import re

from db.models import Link
from worker.rag import QAResult

# LLM обычно сам пишет ссылки в тексте ответа markdown-синтаксисом [title](url) —
# конвертируем это в кликабельный <a>, а не просто экранируем как текст.
_MD_LINK_RE = re.compile(r"\[([^\[\]]+)\]\((https?://[^\s()]+)\)")


def _link_html(url: str, title: str | None) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(title or url)}</a>'


def _render_answer_html(answer: str) -> str:
    """Экранирует текст ответа и превращает [title](url) в кликабельные ссылки."""
    parts: list[str] = []
    last_end = 0
    for m in _MD_LINK_RE.finditer(answer):
        parts.append(html.escape(answer[last_end : m.start()]))
        parts.append(_link_html(m.group(2), m.group(1)))
        last_end = m.end()
    parts.append(html.escape(answer[last_end:]))
    return "".join(parts)


def format_qa_reply_html(result: QAResult) -> str:
    """Для /ask — явного запроса к базе: сам ответ уже содержит кликабельные
    ссылки (см. _render_answer_html), отдельный список источников под ним
    был бы дублированием."""
    return _render_answer_html(result.answer)


def format_link_list_html(links: list[Link]) -> str:
    """Для /search — краткий список ссылок кликабельными заголовками."""
    return "\n".join(f"- {_link_html(link.url, link.title)}" for link in links)
