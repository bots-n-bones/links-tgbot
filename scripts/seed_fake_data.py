"""Заполняет БД синтетическими данными для разработки дашборда без реального бота/LLM.

Запуск: python scripts/seed_fake_data.py (или `make seed`)

Скрипт идемпотентен по url_hash: повторный запуск не плодит дубли, а
досоздаёт недостающее.

Данные подобраны так, чтобы на них было видно то, ради чего существует
каталог, а не просто «40 строк»:

* у каждой ссылки есть **сопроводительное сообщение** — то, что человек
  написал, кидая её в чат. Это главное поле каталога, и на синтетике оно
  должно быть живым, иначе экран выглядит правдоподобнее, чем он есть;
* часть ссылок кидали **несколько разных людей** — это и есть сигнал
  команды (unique_senders), и карточка обязана показать все реплики;
* часть сообщений — **ответы** на чужую реплику (reply_to_text) и
  **пересылки** из каналов (forwarded_from);
* заполнены поля, которые каталог показывает и по которым фильтрует:
  area, usefulness_score с разбивкой, manual_priority, is_tested,
  click_count, is_hidden, статусы обработки.
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

from sqlalchemy import select  # noqa: E402

from db.models import (  # noqa: E402
    Link,
    LinkSource,
    LinkStatus,
    LinkTag,
    ManualPriority,
    SourceType,
    Tag,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from db.session import get_sessionmaker  # noqa: E402

TAG_NAMES = ["ai", "design", "dev", "product", "ml", "backend", "frontend"]
AREAS = ["ai", "design", "coding", "tech", "business", "other"]

# (telegram_id, имя)
SENDERS = [
    (1110001, "Аня"),
    (1110002, "Борис"),
    (1110003, "Вика"),
    (1110004, "Гена"),
    (1110005, "Дима"),
]
CHATS = [(-1001, "Общий чат"), (-1002, "AI-новости"), (-1003, "Продукт")]

# Заготовки материалов: домен, заголовок, описание, area, теги.
MATERIALS = [
    ("github.com", "vLLM: continuous batching для LLM-инференса",
     "Разбор того, как непрерывная батчинг-очередь поднимает throughput инференса в разы.",
     "ai", ["ai", "ml", "backend"]),
    ("arxiv.org", "Retrieval-augmented generation: что изменилось за год",
     "Обзор подходов к RAG — от наивного поиска по эмбеддингам до реранкинга и гибридного поиска.",
     "ai", ["ai", "ml"]),
    ("habr.com", "Как мы выкинули Redis и не пожалели",
     "Опыт замены кэша на локальный in-memory слой: цифры до и после, где это не сработает.",
     "coding", ["backend", "dev"]),
    ("github.com", "Библиотека для фоновых задач без Celery",
     "Лёгкая очередь на Postgres: без брокера, с ретраями и наблюдаемостью из коробки.",
     "coding", ["backend", "dev"]),
    ("figma.com", "Дизайн-система: токены вместо компонентов",
     "Почему начинать надо с ролей и токенов, а не со сборки библиотеки компонентов.",
     "design", ["design", "frontend"]),
    ("medium.com", "Плотные интерфейсы: чему учит Bloomberg Terminal",
     "Информационная плотность как продуктовое требование, а не как вкусовщина.",
     "design", ["design", "product"]),
    ("youtube.com", "Час про эмбеддинги без магии",
     "Понятное объяснение векторного поиска: что реально считается и где ломается.",
     "ai", ["ai", "ml"]),
    ("stripe.com", "Как считать unit-экономику SaaS честно",
     "Разбор метрик, которые чаще всего подгоняют под нужный вывод.",
     "business", ["product"]),
    ("github.com", "pgvector в проде: индексы и подводные камни",
     "HNSW против IVFFlat, размер индекса, скорость вставки, когда всё это разваливается.",
     "coding", ["backend", "ml"]),
    ("news.ycombinator.com", "Обсуждение: нужен ли вообще отдельный вектор-стор",
     "Тред, в котором сходятся аргументы за Postgres и за специализированные базы.",
     "tech", ["backend", "ml"]),
    ("habr.com", "Телеграм-боты: архитектура, которая не разваливается",
     "Разделение хендлеров, очередей и доменной логики на растущем проекте.",
     "coding", ["backend", "dev"]),
    ("web.dev", "Core Web Vitals: что правда влияет на конверсию",
     "Какие метрики двигают деньги, а какие только успокаивают отчёт.",
     "tech", ["frontend", "product"]),
]

# Сопроводительные сообщения — то, ради чего каталог вообще читают.
NOTES = [
    "смотрите, это ровно наш кейс — можно выкинуть свой велосипед",
    "тут есть цифры, а не рассуждения. читается за 10 минут",
    "кажется, это заменит нам две тулзы сразу",
    "держите, вчера как раз про это спорили",
    "не бесспорно, но аргументы сильные. предлагаю обсудить в понедельник",
    "самая внятная статья на тему, что я видел",
    "особенно раздел про индексы — там прям про нашу боль",
    "закину сюда, чтобы не потерять. надо будет попробовать на выходных",
    "автор тот же, что писал про очереди. у него всегда по делу",
    "если коротко: мы делаем это неправильно последние полгода",
    "может пригодиться, когда дойдём до второго этапа",
    "прочитал целиком, рекомендую. вторую половину можно пропустить",
]

REPLIES = [
    "а есть что-нибудь почитать про векторный поиск?",
    "кто-нибудь трогал pgvector в бою?",
    "мы же хотели переделать очереди — есть идеи?",
    "нужен referenceдля дизайн-системы, накидайте",
]

FORWARDS = ["AI-дайджест", "Техно-лента", "Продуктовые заметки", "Заметки backend-разработчика"]


def fake_hash(n: int) -> str:
    return hashlib.sha256(f"seed-link-{n}".encode()).hexdigest()


async def _ensure_workspace_and_users(session) -> tuple[int, list[tuple[int, str]]]:
    """Возвращает (workspace_id, [(user_id, имя), ...]).

    Переиспользует первый существующий workspace — тот самый "Default",
    который заводит бэкфилл миграции c1d2e3f4a5b6, — чтобы сид не расходился
    с тем, куда бот кладёт данные по умолчанию (shared/workspace.py).
    """
    workspace = await session.scalar(select(Workspace).order_by(Workspace.id).limit(1))
    if workspace is None:
        workspace = Workspace(name="Bots & Bones")
        session.add(workspace)
        await session.flush()

    users: list[tuple[int, str]] = []
    for idx, (telegram_id, name) in enumerate(SENDERS):
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            user = User(telegram_id=telegram_id, full_name=name, username=f"user{telegram_id}")
            session.add(user)
            await session.flush()
        membership = await session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user.id,
            )
        )
        if membership is None:
            session.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    # первый сид-пользователь — владелец, остальные участники
                    role=WorkspaceRole.owner if idx == 0 else WorkspaceRole.member,
                )
            )
        users.append((user.id, name))

    await session.flush()
    return workspace.id, users


async def seed(n_links: int = 40) -> None:
    random.seed(20260909)  # воспроизводимый набор: одинаковые скриншоты между запусками
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        workspace_id, users = await _ensure_workspace_and_users(session)

        tags: dict[str, Tag] = {}
        for name in TAG_NAMES:
            tag = await session.scalar(
                select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == name)
            )
            if tag is None:
                tag = Tag(workspace_id=workspace_id, name=name, slug=name)
                session.add(tag)
                await session.flush()
            tags[name] = tag

        now = datetime.now(UTC)
        created = 0
        for i in range(n_links):
            url_hash = fake_hash(i)
            exists = await session.scalar(
                select(Link.id).where(
                    Link.workspace_id == workspace_id, Link.url_hash == url_hash
                )
            )
            if exists:
                continue

            domain, title, description, area, material_tags = MATERIALS[i % len(MATERIALS)]
            created_at = now - timedelta(days=random.randint(0, 20), hours=random.randint(0, 23))

            # Разбивка полезности — та же шкала, что у worker/llm.UsefulnessScore:
            # depth 0-4 + novelty 0-3 + actionability 0-3.
            depth = random.randint(1, 4)
            novelty = random.randint(0, 3)
            actionability = random.randint(0, 3)

            # Сколько разных людей кинули эту ссылку. Каждая четвёртая —
            # больше одного, иначе на экране не видно, как выглядит сигнал
            # команды.
            n_senders = random.choice([1, 1, 1, 2, 2, 3])
            senders = random.sample(users, k=n_senders)

            status = LinkStatus.done if i % 11 else LinkStatus.fetch_failed
            link = Link(
                workspace_id=workspace_id,
                url=f"https://{domain}/article-{i}",
                normalized_url=f"{domain}/article-{i}",
                url_hash=url_hash,
                title=f"{title}",
                description=description if status is LinkStatus.done else None,
                area=area if status is LinkStatus.done else None,
                usefulness_score=(
                    float(depth + novelty + actionability) if status is LinkStatus.done else None
                ),
                usefulness_breakdown=(
                    {
                        "depth": depth,
                        "novelty": novelty,
                        "actionability": actionability,
                        "total": depth + novelty + actionability,
                    }
                    if status is LinkStatus.done
                    else None
                ),
                domain=domain,
                favicon_url=f"https://{domain}/favicon.ico",
                status=status,
                fetch_error=None if status is LinkStatus.done else "403 Forbidden",
                source_count=n_senders + random.randint(0, 2),
                unique_senders=n_senders,
                priority_score=round(random.uniform(0.5, 12), 2),
                click_count=random.choice([0, 0, 1, 2, 3, 5, 9]),
                manual_priority=random.choice(
                    [ManualPriority.normal, ManualPriority.normal,
                     ManualPriority.high, ManualPriority.low]
                ),
                is_tested=random.random() < 0.25,
                is_hidden=random.random() < 0.08,
                added_by_user_id=senders[0][0],
                created_at=created_at,
                processed_at=created_at if status is LinkStatus.done else None,
            )
            session.add(link)
            await session.flush()

            for tag_name in material_tags:
                session.add(LinkTag(link_id=link.id, tag_id=tags[tag_name].id))

            # По одной реплике на каждого отправителя + возможные повторы от
            # него же: source_count >= unique_senders.
            repeats = link.source_count - n_senders
            for position, (sender_user_id, sender_name) in enumerate(senders):
                chat_id, chat_title = random.choice(CHATS)
                sent_at = created_at + timedelta(hours=position * random.randint(1, 30))
                session.add(
                    LinkSource(
                        link_id=link.id,
                        chat_id=chat_id,
                        chat_title=chat_title,
                        message_id=random.randint(1, 100000),
                        sender_id=next(t for t, n in SENDERS if n == sender_name),
                        sender_name=sender_name,
                        message_text=random.choice(NOTES),
                        reply_to_text=random.choice(REPLIES) if random.random() < 0.3 else None,
                        forwarded_from=random.choice(FORWARDS) if random.random() < 0.2 else None,
                        source_type=SourceType.group,
                        created_at=sent_at,
                    )
                )
            for _ in range(repeats):
                chat_id, chat_title = random.choice(CHATS)
                _, sender_name = random.choice(senders)
                session.add(
                    LinkSource(
                        link_id=link.id,
                        chat_id=chat_id,
                        chat_title=chat_title,
                        message_id=random.randint(1, 100000),
                        sender_id=next(t for t, n in SENDERS if n == sender_name),
                        sender_name=sender_name,
                        message_text=random.choice(NOTES),
                        source_type=SourceType.group,
                        created_at=created_at + timedelta(days=random.randint(1, 5)),
                    )
                )
            created += 1

        await session.commit()
        print(
            f"Workspace {workspace_id}: добавлено {created} ссылок "
            f"(всего запрошено {n_links}), пользователей {len(users)}."
        )
        print("Пользователь для входа:", users[0])


if __name__ == "__main__":
    asyncio.run(seed())
