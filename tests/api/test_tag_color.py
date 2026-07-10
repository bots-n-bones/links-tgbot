from api.templates_env import _TAG_COLOR_VARS, clicks_label, tag_color


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


def test_clicks_label_few():
    assert clicks_label(2) == "перехода"
    assert clicks_label(3) == "перехода"
    assert clicks_label(4) == "перехода"
    assert clicks_label(22) == "перехода"


def test_clicks_label_many():
    assert clicks_label(0) == "переходов"
    assert clicks_label(5) == "переходов"
    assert clicks_label(11) == "переходов"
    assert clicks_label(12) == "переходов"
    assert clicks_label(111) == "переходов"
