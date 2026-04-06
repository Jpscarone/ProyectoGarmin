from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.athlete import Athlete


class WeeklyAnalysis(Base):
    __tablename__ = "weekly_analyses"
    __table_args__ = (
        UniqueConstraint("athlete_id", "week_start_date", name="uq_weekly_analysis_athlete_week_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    week_start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    analysis_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v2", server_default="v2")
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    summary_short: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_natural: Mapped[str | None] = mapped_column(Text, nullable=True)
    coach_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_week_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)

    total_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sessions_by_sport: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    time_in_zones: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    intensity_distribution: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    planned_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compliance_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    load_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    consistency_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fatigue_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    balance_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llm_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete"] = relationship(back_populates="weekly_analyses")
