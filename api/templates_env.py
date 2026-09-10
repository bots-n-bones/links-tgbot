import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from api.changelog import CURRENT_VERSION
from worker.llm import AREA_CHOICES

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Детерминированный цвет тега по его имени (не по позиции в списке) — один и
# тот же тег выглядит одинаково на всех карточках. Значения — CSS custom
# properties, объявленные в base.html.
_TAG_COLOR_VARS = ["--peach", "--cyan", "--yellow", "--green", "--lilac"]


def tag_color(name: str) -> str:
    # md5 вместо суммы кодов символов — короткие похожие английские слова
    # (ai/ml/dev/backend...) давали почти одинаковую сумму и коллапсировали
    # в 1-2 цвета из 5.
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(_TAG_COLOR_VARS)
    return _TAG_COLOR_VARS[idx]


# В чате человек кидает ссылку вместе с репликой, и сама ссылка в тексте
# сообщения нам в карточке не нужна — нужна реплика. Если кроме ссылки в
# сообщении ничего не было, возвращаем None: карточка должна показать, что
# комментария не было, а не пустую цитату.
_URL_IN_TEXT_RE = re.compile(r"https?://\S+")


def message_note(text: str | None) -> str | None:
    without_url = _URL_IN_TEXT_RE.sub("", text or "")
    return without_url.strip(" \t\n\r\u2014\u2013-:,") or None


def age_label(moment: datetime | None) -> str:
    """Возраст словами: «вчера» и «3 дня назад» читаются быстрее даты.

    Точная дата остаётся в title — она нужна редко, а сканировать список
    приходится всё время."""
    if moment is None:
        return "—"
    now = datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    days = (now - moment).days
    if days <= 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days < 7:
        return f"{days} дня назад" if days < 5 else f"{days} дней назад"
    if days < 31:
        weeks = days // 7
        return "неделю назад" if weeks == 1 else f"{weeks} недели назад"
    months = days // 30
    if months < 12:
        return "месяц назад" if months == 1 else f"{months} мес. назад"
    return moment.strftime("%d.%m.%Y")


def clicks_label(count: int) -> str:
    """Русские формы множественного числа для счётчика переходов.

    Интерфейс русскоязычный, и "3 clicks с дашборда" — это не мелочь
    стиля: смешанный язык в одной строке читается как недоделка."""
    if 11 <= count % 100 <= 14:
        return "переходов"
    return {1: "переход", 2: "перехода", 3: "перехода", 4: "перехода"}.get(count % 10, "переходов")


# Area — небольшой фиксированный набор (worker.llm.AREA_CHOICES), поэтому цвет
# закреплён вручную, а не по хешу — так каждая area узнаваема с первого взгляда.
_AREA_COLOR_MAP = {
    "ai": "--cyan",
    "design": "--lilac",
    "coding": "--yellow",
    "tech": "--green",
    "business": "--peach",
    "other": "--text-faint",
}


def area_color(area: str | None) -> str:
    return _AREA_COLOR_MAP.get(area or "other", "--text-faint")


templates.env.globals["tag_color"] = tag_color
templates.env.globals["area_color"] = area_color
templates.env.globals["clicks_label"] = clicks_label
templates.env.globals["message_note"] = message_note
templates.env.globals["age_label"] = age_label
templates.env.globals["current_version"] = CURRENT_VERSION
templates.env.globals["area_choices"] = AREA_CHOICES
templates.env.globals["swatch_colors"] = _TAG_COLOR_VARS
