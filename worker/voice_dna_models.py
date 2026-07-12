"""Pydantic-схемы Voice DNA pipeline (TZ_CHANNELS.md §7.2, §7.3, §7.5).

Все поля со значениями по умолчанию — ответ LLM валидируется permissively
(как TagDescriptionResult/PostClassification в worker/llm.py): частично
неполный JSON не должен ронять job, лишние поля отбрасываются pydantic'ом.
"""

from pydantic import BaseModel, Field, field_validator


def _coerce_str_list(v: object) -> object:
    """The aggregate/sections LLM calls sometimes return a labeled object
    instead of a flat array for a `list[str]` field (e.g. key_insights as
    {"view_correlation": "...", "hook_efficacy": "..."} instead of a list) —
    a real prod failure (pydantic ValidationError) rather than a hypothetical
    one. Flatten instead of rejecting, so a schema slip doesn't fail the job."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [f"{key}: {value}" for key, value in v.items()]
    if isinstance(v, list):
        return [item if isinstance(item, str) else str(item) for item in v]
    return [str(v)]


class PostVoiceAnalysis(BaseModel):
    post_id: int
    hook_type: str = "none"
    body_structure: str = "single_block"
    close_type: str = "none"
    register: str = "conversational"
    specificity: str = "medium"
    ethos_pathos_logos: dict[str, float] = Field(default_factory=dict)
    punctuation_style: str = "minimal"
    persona_markers: list[str] = Field(default_factory=list)
    taboos_observed: list[str] = Field(default_factory=list)
    confidence: float = 0.5

    _coerce_lists = field_validator("persona_markers", "taboos_observed", mode="before")(
        _coerce_str_list
    )


class PostVoiceAnalysisBatch(BaseModel):
    items: list[PostVoiceAnalysis] = Field(default_factory=list)


class ContentPillar(BaseModel):
    topic: str
    share: float = 0.0


class UnderTheHood(BaseModel):
    surface_markers: str = ""
    structural_habits: str = ""
    cognitive_patterns: str = ""
    taboos: list[str] = Field(default_factory=list)
    signature_lexicon: str = ""
    cheat_code: str = ""

    _coerce_lists = field_validator("taboos", mode="before")(_coerce_str_list)


class VoiceDnaProfile(BaseModel):
    confidence: float = 0.5
    voice_identity: str = ""
    dominant_template: str = ""
    template_frequency: float = 0.0
    tone_dimensions: dict[str, float] = Field(default_factory=dict)
    tone_of_voice: str = ""
    successful_formats: str = ""
    structural_dna: str = ""
    rhythm_analysis: str = ""
    opening_moves: str = ""
    closing_moves: str = ""
    lexical_profile: str = ""
    rhetoric_strategy: str = ""
    content_strategy: str = ""
    engagement_patterns: str = ""
    key_insights: list[str] = Field(default_factory=list)
    hidden_patterns: list[str] = Field(default_factory=list)
    under_the_hood: UnderTheHood = Field(default_factory=UnderTheHood)
    recommendations: list[str] = Field(default_factory=list)
    content_pillars: list[ContentPillar] = Field(default_factory=list)
    generation_rules: list[str] = Field(default_factory=list)
    radar: dict[str, float] = Field(default_factory=dict)

    _coerce_lists = field_validator(
        "key_insights", "hidden_patterns", "recommendations", "generation_rules", mode="before"
    )(_coerce_str_list)


class SummarySection(BaseModel):
    voice_identity: str = ""
    tone_of_voice: str = ""
    successful_formats: str = ""


class StructureSection(BaseModel):
    structural_dna: str = ""
    rhythm_analysis: str = ""
    opening_moves: str = ""
    closing_moves: str = ""


class ContentSection(BaseModel):
    lexical_profile: str = ""
    rhetoric_strategy: str = ""
    content_strategy: str = ""
    engagement_patterns: str = ""


class InsightsSection(BaseModel):
    key_insights: list[str] = Field(default_factory=list)
    hidden_patterns: list[str] = Field(default_factory=list)
    under_the_hood: UnderTheHood = Field(default_factory=UnderTheHood)
    recommendations: list[str] = Field(default_factory=list)

    _coerce_lists = field_validator(
        "key_insights", "hidden_patterns", "recommendations", mode="before"
    )(_coerce_str_list)


class ReportSections(BaseModel):
    summary: SummarySection = Field(default_factory=SummarySection)
    structure: StructureSection = Field(default_factory=StructureSection)
    content: ContentSection = Field(default_factory=ContentSection)
    insights: InsightsSection = Field(default_factory=InsightsSection)
