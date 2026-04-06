from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.athlete import Athlete
    from app.db.models.garmin_activity import GarminActivity
    from app.db.models.planned_session import PlannedSession


class SessionAnalysis(Base):
    __tablename__ = "session_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    planned_session_id: Mapped[int] = mapped_column(ForeignKey("planned_sessions.id"), nullable=False, index=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("garmin_activities.id"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    analysis_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v2", server_default="v2")
    trigger_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    summary_short: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_natural: Mapped[str | None] = mapped_column(Text, nullable=True)
    coach_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)

    compliance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    execution_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    control_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fatigue_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    heat_impact_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cardiac_drift_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hydration_risk_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pace_instability_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    manual_review_needed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llm_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete"] = relationship(back_populates="session_analyses")
    planned_session: Mapped["PlannedSession"] = relationship(back_populates="session_analyses")
    activity: Mapped["GarminActivity"] = relationship(back_populates="session_analyses")
