"""Обычный ответ на свободные сообщения (не /ask): без поиска по базе
ссылок и без RAG-системного промпта, который явно требует цитировать
материалы — иначе даже "как дела?" получает список "релевантных ссылок"."""

from shared.config import get_settings
from worker.llm import get_llm_client

CASUAL_CHAT_SYSTEM_PROMPT = """Ты дружелюбный ассистент Telegram-бота, который собирает
полезные ссылки команды. Сейчас с тобой просто общаются в чате, а не запрашивают базу ссылок.

Отвечай коротко и по-человечески на реплику пользователя. НЕ упоминай, не
перечисляй и не выдумывай ссылки или статьи — в этом режиме у тебя нет
доступа к базе. Если пользователь явно хочет найти что-то в базе ссылок —
посоветуй команду /ask <вопрос>, но не пытайся ответить по существу вместо неё."""


async def answer_casually(text: str) -> str:
    llm_client = get_llm_client()
    settings = get_settings()
    return await llm_client.complete(
        system_prompt=CASUAL_CHAT_SYSTEM_PROMPT,
        user_prompt=text,
        model=settings.openai_model_mini,
    )
