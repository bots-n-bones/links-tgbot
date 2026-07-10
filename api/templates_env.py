import hashlib
from pathlib import Path

from fastapi.templating import Jinja2Templates

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
    """Русское склонение: 1 переход, 2-4 перехода, 0/5+/11-14 переходов."""
    if count % 10 == 1 and count % 100 != 11:
        return "переход"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "перехода"
    return "переходов"


templates.env.globals["tag_color"] = tag_color
templates.env.globals["clicks_label"] = clicks_label
