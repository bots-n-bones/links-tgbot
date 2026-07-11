import hashlib
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


def clicks_label(count: int) -> str:
    return "click" if count == 1 else "clicks"


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
templates.env.globals["current_version"] = CURRENT_VERSION
templates.env.globals["area_choices"] = AREA_CHOICES
