from __future__ import annotations

from datetime import datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.activity_session_match import ActivitySessionMatch
    from app.db.models.analysis_report import AnalysisReport
    from app.db.models.athlete import Athlete
    from app.db.models.planned_session_step import PlannedSessionStep
    from app.db.models.session_group import SessionGroup
    from app.db.models.training_day import TrainingDay


class PlannedSession(Base):
    __tablename__ = "planned_sessions"
    __table_args__ = (Index("ix_planned_sessions_training_day_order", "training_day_id", "session_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_day_id: Mapped[int] = mapped_column(ForeignKey("training_days.id"), nullable=False, index=True)
    session_group_id: Mapped[int | None] = mapped_column(ForeignKey("session_groups.id"), nullable=True, index=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    sport_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discipline_variant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    planned_start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    expected_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_hr_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_pace_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_power_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_rpe_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_key_session: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    training_day: Mapped["TrainingDay"] = relationship(back_populates="planned_sessions")
    session_group: Mapped["SessionGroup | None"] = relationship(back_populates="planned_sessions")
    athlete: Mapped["Athlete"] = relationship(back_populates="planned_sessions")
    planned_session_steps: Mapped[list["PlannedSessionStep"]] = relationship(
        back_populates="planned_session",
        cascade="all, delete-orphan",
        order_by="PlannedSessionStep.step_order",
    )
    activity_match: Mapped["ActivitySessionMatch | None"] = relationship(
        back_populates="planned_session",
        cascade="all, delete-orphan",
        uselist=False,
    )
    analysis_reports: Mapped[list["AnalysisReport"]] = relationship(
        back_populates="planned_session",
        cascade="all, delete-orphan",
    )
