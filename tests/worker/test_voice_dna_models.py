from worker.voice_dna_models import (
    PostVoiceAnalysis,
    PostVoiceAnalysisBatch,
    ReportSections,
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
