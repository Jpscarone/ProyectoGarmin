from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _clean_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text:
            cleaned.append(text)
    return cleaned


class WeeklyNarrativeStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_type_detected: str = "indeterminada"
    dominant_week_issue: str | None = None
    recommendation_reason: str | None = None
    main_findings: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    positives: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("week_type_detected", "dominant_week_issue", "recommendation_reason", mode="before")
    @classmethod
    def clean_text_field(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _clean_text(value) or ""
        return value

    @field_validator("main_findings", "risks", "positives", "recommendations", "tags", mode="before")
    @classmethod
    def clean_list_field(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _clean_list([value])
        if isinstance(value, list):
            return _clean_list([str(item) for item in value if item is not None])
        return []


class WeeklyNarrativeLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_short: str = ""
    analysis_natural: str = ""
    coach_conclusion: str = ""
    next_week_recommendation: str = ""
    week_type_detected: str = "indeterminada"
    dominant_week_issue: str | None = None
    recommendation_reason: str | None = None
    main_findings: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    positives: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator(
        "summary_short",
        "analysis_natural",
        "coach_conclusion",
        "next_week_recommendation",
        "week_type_detected",
        "dominant_week_issue",
        "recommendation_reason",
        mode="before",
    )
    @classmethod
    def clean_text_field(cls, value: Any) -> str:
        if isinstance(value, str):
            return _clean_text(value) or ""
        if value is None:
            return ""
        return str(value)

    @field_validator("main_findings", "risks", "positives", "recommendations", "tags", mode="before")
    @classmethod
    def clean_list_field(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _clean_list([value])
        if isinstance(value, list):
            return _clean_list([str(item) for item in value if item is not None])
        return []

    def to_structured_output(self) -> WeeklyNarrativeStructuredOutput:
        return WeeklyNarrativeStructuredOutput(
            week_type_detected=self.week_type_detected,
            dominant_week_issue=self.dominant_week_issue,
            recommendation_reason=self.recommendation_reason,
            main_findings=self.main_findings,
            risks=self.risks,
            positives=self.positives,
            recommendations=self.recommendations,
            tags=self.tags,
        )


class WeeklyNarrativeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    narrative_status: str = "completed"
    provider: str | None = None
    model: str | None = None
    summary_short: str = ""
    analysis_natural: str = ""
    coach_conclusion: str = ""
    next_week_recommendation: str = ""
    structured_output: WeeklyNarrativeStructuredOutput = Field(default_factory=WeeklyNarrativeStructuredOutput)
    llm_json: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None

    @classmethod
    def from_llm_output(
        cls,
        output: WeeklyNarrativeLLMOutput,
        *,
        narrative_status: str,
        provider: str | None,
        model: str | None,
        llm_json: dict[str, Any],
        error_message: str | None = None,
    ) -> "WeeklyNarrativeResult":
        return cls(
            narrative_status=narrative_status,
            provider=provider,
            model=model,
            summary_short=output.summary_short,
            analysis_natural=output.analysis_natural,
            coach_conclusion=output.coach_conclusion,
            next_week_recommendation=output.next_week_recommendation,
            structured_output=output.to_structured_output(),
            llm_json=llm_json,
            error_message=error_message,
        )
