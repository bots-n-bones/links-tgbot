"""Форматирование Telegram-ответов со ссылками. Отправляется с parse_mode
HTML, поэтому весь заголовок/текст экранируется html.escape — доверенная
разметка (<a href=...>) добавляется только вокруг него, никогда вокруг
непроверенного контента напрямую."""

import html

from db.models import Link
from worker.rag import QAResult


def _link_html(url: str, title: str | None) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(title or url)}</a>'


def format_qa_reply_html(result: QAResult) -> str:
    """Для /ask — явного запроса к базе: ответ + список источников кликабельными
    заголовками вместо 'title (url)'."""
    lines = [html.escape(result.answer)]
    if result.matched_links:
        lines.append("")
        lines.append("Источники:")
        for m in result.matched_links:
            lines.append(f"- {_link_html(m.url, m.title)} — добавляли {m.source_count} раз")
    return "\n".join(lines)


def format_link_list_html(links: list[Link]) -> str:
    """Для /search — краткий список ссылок кликабельными заголовками."""
    return "\n".join(f"- {_link_html(link.url, link.title)}" for link in links)
