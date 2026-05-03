from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _clean_text_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text:
            cleaned.append(text)
    return cleaned


class InterpretiveFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_over_target_flag: bool | None = None
    distance_over_target_flag: bool | None = None
    elevation_over_target_flag: bool | None = None
    heart_rate_high_flag: bool | None = None
    pace_instability_flag: bool | None = None
    possible_heat_impact_flag: bool | None = None
    heat_impact_flag: bool | None = None
    cardiac_drift_flag: bool | None = None
    hydration_risk_flag: bool | None = None
    manual_review_needed: bool | None = None


class NarrativeStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_type_detected: str = "indeterminada"
    overall_assessment: str = "revision"
    key_positive_points: list[str] = Field(default_factory=list)
    key_risk_points: list[str] = Field(default_factory=list)
    practical_recommendations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    interpretive_flags: InterpretiveFlags = Field(default_factory=InterpretiveFlags)

    @field_validator("session_type_detected", "overall_assessment", mode="before")
    @classmethod
    def clean_text_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _clean_text(value) or ""
        return value

    @field_validator(
        "key_positive_points",
        "key_risk_points",
        "practical_recommendations",
        "tags",
        mode="before",
    )
    @classmethod
    def clean_text_list_fields(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _clean_text_list([value])
        if isinstance(value, list):
            return _clean_text_list([str(item) for item in value if item is not None])
        return []


class NarrativeLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_short: str = ""
    analysis_natural: str = ""
    coach_conclusion: str = ""
    next_recommendation: str = ""
    session_type_detected: str = "indeterminada"
    overall_assessment: str = "revision"
    key_positive_points: list[str] = Field(default_factory=list)
    key_risk_points: list[str] = Field(default_factory=list)
    practical_recommendations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    interpretive_flags: InterpretiveFlags = Field(default_factory=InterpretiveFlags)

    @field_validator(
        "summary_short",
        "analysis_natural",
        "coach_conclusion",
        "next_recommendation",
        "session_type_detected",
        "overall_assessment",
        mode="before",
    )
    @classmethod
    def clean_text_fields(cls, value: Any) -> str:
        if isinstance(value, str):
            return _clean_text(value) or ""
        if value is None:
            return ""
        return str(value)

    @field_validator(
        "key_positive_points",
        "key_risk_points",
        "practical_recommendations",
        "tags",
        mode="before",
    )
    @classmethod
    def clean_text_list_fields(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _clean_text_list([value])
        if isinstance(value, list):
            return _clean_text_list([str(item) for item in value if item is not None])
        return []

    @field_validator("interpretive_flags", mode="before")
    @classmethod
    def clean_interpretive_flags(cls, value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, InterpretiveFlags):
            return value
        if isinstance(value, dict):
            allowed_keys = set(InterpretiveFlags.model_fields.keys())
            return {key: bool(item) if item is not None else None for key, item in value.items() if key in allowed_keys}
        return {}

    def to_structured_output(self) -> NarrativeStructuredOutput:
        return NarrativeStructuredOutput(
            session_type_detected=self.session_type_detected or "indeterminada",
            overall_assessment=self.overall_assessment or "revision",
            key_positive_points=self.key_positive_points,
            key_risk_points=self.key_risk_points,
            practical_recommendations=self.practical_recommendations,
            tags=self.tags,
            interpretive_flags=self.interpretive_flags,
        )


class NarrativeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    narrative_status: str = "completed"
    provider: str | None = None
    model: str | None = None
    summary_short: str = ""
    analysis_natural: str = ""
    coach_conclusion: str = ""
    next_recommendation: str = ""
    quick_takeaway: str = ""
    structured_output: NarrativeStructuredOutput = Field(default_factory=NarrativeStructuredOutput)
    llm_json: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None

    @classmethod
    def from_llm_output(
        cls,
        output: NarrativeLLMOutput,
        *,
        narrative_status: str,
        provider: str | None,
        model: str | None,
        llm_json: dict[str, Any],
        quick_takeaway: str = "",
        error_message: str | None = None,
    ) -> "NarrativeResult":
        return cls(
            narrative_status=narrative_status,
            provider=provider,
            model=model,
            summary_short=output.summary_short,
            analysis_natural=output.analysis_natural,
            coach_conclusion=output.coach_conclusion,
            next_recommendation=output.next_recommendation,
            quick_takeaway=quick_takeaway,
            structured_output=output.to_structured_output(),
            llm_json=llm_json,
            error_message=error_message,
        )
