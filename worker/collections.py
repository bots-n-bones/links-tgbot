"""Еженедельные тематические подборки (TZ §4.8, промпт §9.3)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from db.models import Collection, Link, LinkSource, LinkTag, Tag
from db.session import get_sessionmaker
from shared.config import get_settings
from worker.llm import get_llm_client

TOP_N_PER_TAG = (
    5  # F-73: топ-N по тегу — уже сортировка по priority_score покрывает "достаточный приоритет"
)

DAILY_TOP3_THEME = "daily-top3"
DAILY_TOP3_WINDOW_DAYS = 7  # "новые материалы" — активность за последнюю неделю, не только за сутки
DAILY_TOP3_LIMIT = 3

COLLECTION_SYSTEM_PROMPT = (
    "Ты аналитик, который готовит для команды еженедельную подборку полезных материалов."
)

COLLECTION_PROMPT_TEMPLATE = """Вот ссылки, которые команда сохраняла за неделю по теме "{theme}":

{links_with_descriptions_and_counts}

Составь тематическую подборку на русском:
1. Главное за неделю (2-3 предложения)
2. Топ материалов по востребованности (с кратким пояснением)
3. Что не пропустить
4. Наблюдения (новые тренды, теги)

Формат: markdown."""


async def _links_for_tag_in_window(
    session, tag_name: str, period_start: datetime, period_end: datetime
) -> list[Link]:
    link_ids_for_tag = (
        select(LinkTag.link_id).join(Tag, Tag.id == LinkTag.tag_id).where(Tag.name == tag_name)
    )
    recent_link_ids = select(LinkSource.link_id).where(
        LinkSource.created_at >= period_start, LinkSource.created_at < period_end
    )
    stmt = (
        select(Link)
        .where(
            Link.id.in_(link_ids_for_tag), Link.id.in_(recent_link_ids), Link.is_hidden.is_(False)
        )
        .order_by(Link.priority_score.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


def _format_links_block(links: list[Link]) -> str:
    return "\n".join(
        f"- [{link.title or link.url}]({link.url}) — {link.description or 'без описания'} "
        f"(добавляли {link.source_count} раз, приоритет {link.priority_score:.1f})"
        for link in links
    )


async def generate_daily_top3(*, now: datetime | None = None) -> Collection | None:
    """Ежедневная (Celery Beat, 12:00) подборка топ-3 новых материалов —
    среди ссылок, добавленных за последнюю неделю, по priority_score
    (учитывает, сколько раз и сколько разных людей их кидали в Telegram).
    Хранится как Collection с theme=DAILY_TOP3_THEME, без LLM — чисто
    алгоритмический отбор, показывается отдельным блоком на дашборде."""
    sessionmaker = get_sessionmaker()

    period_end = now or datetime.now(UTC)
    period_start = period_end - timedelta(days=DAILY_TOP3_WINDOW_DAYS)

    async with sessionmaker() as session:
        recent_link_ids = select(LinkSource.link_id).where(
            LinkSource.created_at >= period_start, LinkSource.created_at < period_end
        )
        stmt = (
            select(Link)
            .where(Link.id.in_(recent_link_ids), Link.is_hidden.is_(False))
            .order_by(Link.priority_score.desc())
            .limit(DAILY_TOP3_LIMIT)
        )
        top_links = list((await session.execute(stmt)).scalars().all())
        if not top_links:
            return None

        collection = Collection(
            title="Топ-3 новых материала",
            theme=DAILY_TOP3_THEME,
            period_start=period_start.date(),
            period_end=period_end.date(),
            summary_md="Автоматический отбор по востребованности за последнюю неделю.",
            link_ids=[link.id for link in top_links],
        )
        session.add(collection)
        await session.commit()
        await session.refresh(collection)
        return collection


async def generate_weekly_collection(*, now: datetime | None = None) -> Collection | None:
    """F-70..74: группировка по тегам за 7 дней, LLM-подборка. Возвращает None,
    если за период не набралось материала ни по одному тегу."""
    settings = get_settings()
    llm_client = get_llm_client()
    sessionmaker = get_sessionmaker()

    period_end = now or datetime.now(UTC)
    period_start = period_end - timedelta(days=7)

    async with sessionmaker() as session:
        all_tag_names = (await session.execute(select(Tag.name))).scalars().all()

        theme_sections: list[str] = []
        all_link_ids: set[int] = set()
        for tag_name in all_tag_names:
            links = await _links_for_tag_in_window(session, tag_name, period_start, period_end)
            if not links:
                continue
            top_links = links[:TOP_N_PER_TAG]
            theme_sections.append(f"### {tag_name}\n{_format_links_block(top_links)}")
            all_link_ids.update(link.id for link in top_links)

        if not theme_sections:
            return None

        theme = f"{period_start.strftime('%d.%m')}–{period_end.strftime('%d.%m')}"
        user_prompt = COLLECTION_PROMPT_TEMPLATE.format(
            theme=theme, links_with_descriptions_and_counts="\n\n".join(theme_sections)
        )
        summary_md = await llm_client.complete(
            system_prompt=COLLECTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.openai_model_mini,
        )

        collection = Collection(
            title=f"Подборка за {theme}",
            theme=theme,
            period_start=period_start.date(),
            period_end=period_end.date(),
            summary_md=summary_md,
            link_ids=sorted(all_link_ids),
        )
        session.add(collection)
        await session.commit()
        await session.refresh(collection)
        return collection
