from api.templates_env import _TAG_COLOR_VARS, area_color, clicks_label, tag_color


def test_tag_color_is_deterministic():
    assert tag_color("ai") == tag_color("ai")


def test_tag_color_returns_known_css_var():
    assert tag_color("design") in _TAG_COLOR_VARS


def test_tag_color_varies_by_name():
    colors = {tag_color(name) for name in ["ai", "design", "dev", "product", "ml", "backend"]}
    assert len(colors) > 1  # не все теги должны схлопнуться в один цвет


def test_clicks_label_singular():
    assert clicks_label(1) == "click"


def test_clicks_label_plural():
    assert clicks_label(0) == "clicks"
    assert clicks_label(2) == "clicks"
    assert clicks_label(11) == "clicks"
    assert clicks_label(111) == "clicks"


def test_area_color_is_fixed_per_area():
    assert area_color("ai") == "--cyan"
    assert area_color("design") == "--lilac"


def test_area_color_falls_back_for_unknown_or_missing():
    assert area_color(None) == "--text-faint"
    assert area_color("nonsense") == "--text-faint"
