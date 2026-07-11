"""Бэкфилл embedding для постов, добавленных до появления единого поиска
Links+Posts. Запуск: python scripts/backfill_post_embeddings.py"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from db.models import Post  # noqa: E402
from db.session import get_sessionmaker  # noqa: E402
from worker.embeddings import get_embedding_client  # noqa: E402


async def main() -> None:
    embedding_client = get_embedding_client()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        posts = (
            (await session.execute(select(Post).where(Post.embedding.is_(None))))
            .scalars()
            .all()
        )
        print(f"{len(posts)} постов без embedding")

        for i, post in enumerate(posts, start=1):
            text = f"{post.text or ''} {post.summary or ''}".strip()
            post.embedding = await embedding_client.embed(text or post.chat_title or "post")
            print(f"[{i}/{len(posts)}] post_id={post.id} готово")
            if i % 20 == 0:
                await session.commit()

        await session.commit()
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
