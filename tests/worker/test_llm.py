from worker.llm import AREA_CHOICES, normalize_area


def test_normalize_area_accepts_known_values():
    for area in AREA_CHOICES:
        assert normalize_area(area) == area


def test_normalize_area_is_case_insensitive():
    assert normalize_area("AI") == "ai"


def test_normalize_area_falls_back_to_other_for_unknown():
    assert normalize_area("crypto") == "other"
    assert normalize_area(None) == "other"
    assert normalize_area("") == "other"
