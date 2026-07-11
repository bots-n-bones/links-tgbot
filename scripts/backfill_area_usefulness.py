"""Бэкфилл area/usefulness_score для ссылок, добавленных до появления этих полей.

Классифицирует по уже сохранённым title/description (без повторного fetch
страницы) — дёшево и быстро. Запуск: python scripts/backfill_area_usefulness.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from db.models import Link  # noqa: E402
from db.session import get_sessionmaker  # noqa: E402
from shared.config import get_settings  # noqa: E402
from worker.llm import OpenAILLMClient, normalize_area  # noqa: E402


async def main() -> None:
    settings = get_settings()
    llm = OpenAILLMClient(
        api_key=settings.openai_api_key,
        model_mini=settings.openai_model_mini,
        model_report=settings.openai_model_report,
    )
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(
            select(Link).where(Link.area.is_(None) | Link.usefulness_score.is_(None))
        )
        links = result.scalars().all()
        print(f"{len(links)} ссылок без area/usefulness")

        for i, link in enumerate(links, start=1):
            try:
                classification = await llm.describe_link(
                    url=link.url,
                    title=link.title,
                    og_description=link.description,
                    page_text=link.description or "",
                    message_text=None,
                    sender=None,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[{i}/{len(links)}] {link.url} — ошибка LLM: {exc}")
                continue

            link.area = normalize_area(classification.area)
            link.usefulness_score = classification.usefulness.total
            link.usefulness_breakdown = classification.usefulness.as_breakdown()
            print(f"[{i}/{len(links)}] {link.url} -> area={link.area} score={link.usefulness_score}")

            if i % 20 == 0:
                await session.commit()

        await session.commit()
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
