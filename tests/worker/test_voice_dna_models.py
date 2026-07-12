from worker.voice_dna_models import (
    InsightsSection,
    PostVoiceAnalysis,
    PostVoiceAnalysisBatch,
    ReportSections,
    UnderTheHood,
    VoiceDnaProfile,
)


def test_post_voice_analysis_drops_extra_fields():
    analysis = PostVoiceAnalysis.model_validate(
        {"post_id": 1, "hook_type": "bold_claim", "unexpected_field": "ignored"}
    )
    assert analysis.post_id == 1
    assert analysis.hook_type == "bold_claim"
    assert not hasattr(analysis, "unexpected_field")


def test_post_voice_analysis_batch_parses_items():
    batch = PostVoiceAnalysisBatch.model_validate(
        {"items": [{"post_id": 1}, {"post_id": 2, "hook_type": "quote"}]}
    )
    assert len(batch.items) == 2
    assert batch.items[1].hook_type == "quote"


def test_post_voice_analysis_batch_defaults_to_empty():
    batch = PostVoiceAnalysisBatch.model_validate({})
    assert batch.items == []


def test_voice_dna_profile_fills_defaults_for_partial_input():
    profile = VoiceDnaProfile.model_validate(
        {"voice_identity": "A punchy, direct newsletter voice."}
    )
    assert profile.voice_identity == "A punchy, direct newsletter voice."
    assert profile.confidence == 0.5
    assert profile.key_insights == []
    assert profile.under_the_hood.cheat_code == ""
    assert profile.content_pillars == []


def test_voice_dna_profile_parses_nested_content_pillars():
    profile = VoiceDnaProfile.model_validate(
        {"content_pillars": [{"topic": "product updates", "share": 0.4}]}
    )
    assert profile.content_pillars[0].topic == "product updates"
    assert profile.content_pillars[0].share == 0.4


def test_report_sections_fills_nested_defaults():
    sections = ReportSections.model_validate({"summary": {"voice_identity": "x"}})
    assert sections.summary.voice_identity == "x"
    assert sections.structure.structural_dna == ""
    assert sections.insights.key_insights == []


def test_voice_dna_profile_coerces_dict_key_insights_to_list():
    # Real prod failure: the aggregate LLM call returned key_insights as a
    # labeled object instead of an array, and pydantic rejected it outright.
    profile = VoiceDnaProfile.model_validate(
        {
            "key_insights": {
                "view_correlation": "Posts with questions get 2x views.",
                "hook_efficacy": "Bold claims outperform single_block structures.",
            }
        }
    )
    assert profile.key_insights == [
        "view_correlation: Posts with questions get 2x views.",
        "hook_efficacy: Bold claims outperform single_block structures.",
    ]


def test_voice_dna_profile_coerces_string_and_none_list_fields():
    profile = VoiceDnaProfile.model_validate(
        {"hidden_patterns": "Only one pattern, sent as a bare string.", "recommendations": None}
    )
    assert profile.hidden_patterns == ["Only one pattern, sent as a bare string."]
    assert profile.recommendations == []


def test_under_the_hood_coerces_dict_taboos():
    hood = UnderTheHood.model_validate({"taboos": {"topic": "politics"}})
    assert hood.taboos == ["topic: politics"]


def test_insights_section_coerces_dict_key_insights():
    insights = InsightsSection.model_validate({"key_insights": {"a": "one", "b": "two"}})
    assert insights.key_insights == ["a: one", "b: two"]
