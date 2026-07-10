"""Форматирование ответов RAG для Telegram (переиспользуется commands.py и private.py)."""

from worker.rag import QAResult


def format_qa_reply(result: QAResult) -> str:
    lines = [result.answer]
    if result.matched_links:
        lines.append("")
        lines.append("Источники:")
        for m in result.matched_links:
            lines.append(f"- {m.title or m.url} ({m.url}) — добавляли {m.source_count} раз")
    return "\n".join(lines)
