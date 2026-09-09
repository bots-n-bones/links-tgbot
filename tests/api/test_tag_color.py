from api.templates_env import _TAG_COLOR_VARS, area_color, clicks_label, tag_color


def test_tag_color_is_deterministic():
    assert tag_color("ai") == tag_color("ai")


def test_tag_color_returns_known_css_var():
    assert tag_color("design") in _TAG_COLOR_VARS


def test_tag_color_varies_by_name():
    colors = {tag_color(name) for name in ["ai", "design", "dev", "product", "ml", "backend"]}
    assert len(colors) > 1  # не все теги должны схлопнуться в один цвет


def test_clicks_label_singular():
    assert clicks_label(1) == "переход"
    assert clicks_label(21) == "переход"


def test_clicks_label_plural():
    assert clicks_label(2) == "перехода"
    assert clicks_label(3) == "перехода"
    assert clicks_label(4) == "перехода"
    assert clicks_label(23) == "перехода"

    assert clicks_label(0) == "переходов"
    assert clicks_label(5) == "переходов"
    assert clicks_label(111) == "переходов"


def test_clicks_label_handles_the_teens():
    """11-14 — исключение из правила по последней цифре: «11 переходов»,
    а не «11 переход»."""
    for count in (11, 12, 13, 14, 111, 112):
        assert clicks_label(count) == "переходов"


def test_area_color_is_fixed_per_area():
    assert area_color("ai") == "--cyan"
    assert area_color("design") == "--lilac"


def test_area_color_falls_back_for_unknown_or_missing():
    assert area_color(None) == "--text-faint"
    assert area_color("nonsense") == "--text-faint"
