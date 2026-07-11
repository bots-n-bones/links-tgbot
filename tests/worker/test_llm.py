from worker.llm import AREA_CHOICES, UsefulnessScore, normalize_area


def test_normalize_area_accepts_known_values():
    for area in AREA_CHOICES:
        assert normalize_area(area) == area


def test_normalize_area_is_case_insensitive():
    assert normalize_area("AI") == "ai"


def test_normalize_area_falls_back_to_other_for_unknown():
    assert normalize_area("crypto") == "other"
    assert normalize_area(None) == "other"
    assert normalize_area("") == "other"


def test_usefulness_score_total_sums_components():
    score = UsefulnessScore(depth=3, novelty=2, actionability=1)
    assert score.total == 6.0
    assert score.as_breakdown() == {"depth": 3, "novelty": 2, "actionability": 1, "total": 6}


def test_usefulness_score_clamps_out_of_range_values():
    # LLM иногда может вернуть значение вне рубрики — не даём вылезти за диапазон
    score = UsefulnessScore(depth=99, novelty=-5, actionability=3)
    assert score.total == 4.0 + 0.0 + 3.0
    breakdown = score.as_breakdown()
    assert breakdown["depth"] == 4
    assert breakdown["novelty"] == 0
    assert breakdown["actionability"] == 3


def test_usefulness_score_defaults_to_zero():
    assert UsefulnessScore().total == 0.0
