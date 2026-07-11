"""Диагностика: печатает посты с area='other' и пустым text/summary, чтобы
понять, откуда они взялись (обычно — сообщения без текста, куда LLM не смог
ничего классифицировать). Запуск: python scripts/inspect_posts.py"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from db.models import Post  # noqa: E402
from db.session import get_sessionmaker  # noqa: E402


async def main() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        posts = (await session.execute(select(Post).order_by(Post.id))).scalars().all()
        print(f"{len(posts)} постов всего")

        suspicious = [p for p in posts if p.area == "other" and not (p.text or "").strip()]
        print(f"{len(suspicious)} постов с area=other и пустым text")
        for p in suspicious:
            print(
                f"id={p.id} chat_id={p.chat_id} message_id={p.message_id} "
                f"chat_title={p.chat_title!r} sender_id={p.sender_id} "
                f"summary={p.summary!r} post_url={p.post_url} created_at={p.created_at}"
            )


if __name__ == "__main__":
    asyncio.run(main())
