"""Заполняет БД синтетическими данными для разработки дашборда без реального бота/LLM.

Запуск: python scripts/seed_fake_data.py (или `make seed`)
"""

import asyncio
import hashlib
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Editable install не всегда регистрирует пакеты при прямом запуске
# `python scripts/seed_fake_data.py` (sys.path[0] тогда — папка scripts/,
# не корень репозитория) — добавляем корень явно для надёжности.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.models import Link, LinkSource, LinkStatus, LinkTag, SourceType, Tag  # noqa: E402
from db.session import get_sessionmaker  # noqa: E402

DOMAINS = ["habr.com", "github.com", "arxiv.org", "youtube.com", "medium.com"]
TAG_NAMES = ["ai", "design", "dev", "product", "ml", "backend", "frontend"]
SENDERS = [
    (111, "Аня"),
    (222, "Борис"),
    (333, "Вика"),
    (444, "Гена"),
    (555, "Дима"),
]
CHATS = [(-1001, "Общий чат"), (-1002, "AI-новости"), (-1003, "Продукт")]


def fake_hash(n: int) -> str:
    return hashlib.sha256(f"seed-link-{n}".encode()).hexdigest()


async def seed(n_links: int = 40) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        tags = {name: Tag(name=name, slug=name) for name in TAG_NAMES}
        session.add_all(tags.values())
        await session.flush()

        now = datetime.now(UTC)
        for i in range(n_links):
            domain = random.choice(DOMAINS)
            created_at = now - timedelta(days=random.randint(0, 20))
            link = Link(
                url=f"https://{domain}/article-{i}",
                normalized_url=f"{domain}/article-{i}",
                url_hash=fake_hash(i),
                title=f"Материал #{i} про {random.choice(TAG_NAMES)}",
                description=f"Короткое описание материала {i} — зачем он полезен команде.",
                domain=domain,
                favicon_url=f"https://{domain}/favicon.ico",
                status=LinkStatus.done,
                source_count=random.randint(1, 5),
                unique_senders=random.randint(1, 3),
                priority_score=round(random.uniform(0.5, 12), 2),
                created_at=created_at,
                processed_at=created_at,
            )
            session.add(link)
            await session.flush()

            for tag_name in random.sample(TAG_NAMES, k=random.randint(1, 3)):
                session.add(LinkTag(link_id=link.id, tag_id=tags[tag_name].id))

            for _ in range(link.source_count):
                chat_id, chat_title = random.choice(CHATS)
                sender_id, sender_name = random.choice(SENDERS)
                session.add(
                    LinkSource(
                        link_id=link.id,
                        chat_id=chat_id,
                        chat_title=chat_title,
                        message_id=random.randint(1, 100000),
                        sender_id=sender_id,
                        sender_name=sender_name,
                        message_text=f"Смотрите: {link.url}",
                        source_type=SourceType.group,
                        created_at=created_at,
                    )
                )

        await session.commit()
        print(f"Добавлено {n_links} синтетических ссылок.")


if __name__ == "__main__":
    asyncio.run(seed())
