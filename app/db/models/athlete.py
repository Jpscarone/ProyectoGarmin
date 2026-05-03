from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.activity_session_match import ActivitySessionMatch
    from app.db.models.analysis_report import AnalysisReport
    from app.db.models.daily_health_metric import DailyHealthMetric
    from app.db.models.garmin_activity import GarminActivity
    from app.db.models.garmin_account import GarminAccount
    from app.db.models.health_ai_analysis import HealthAiAnalysis
    from app.db.models.goal import Goal
    from app.db.models.planned_session import PlannedSession
    from app.db.models.session_analysis import SessionAnalysis
    from app.db.models.weekly_analysis import WeeklyAnalysis
    from app.db.models.training_day import TrainingDay
    from app.db.models.training_plan import TrainingPlan


class Athlete(Base):
    __tablename__ = "athletes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active", default="active", index=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lactate_threshold_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    running_threshold_pace_sec_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cycling_ftp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    hr_zones_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    power_zones_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pace_zones_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rpe_zones_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_hr_zones: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_power_zones: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_pace_zones: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_rpe_zones: Mapped[str | None] = mapped_column(String(50), nullable=True)
    garmin_profile_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    garmin_profile_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    goals: Mapped[list["Goal"]] = relationship(back_populates="athlete", cascade="all, delete-orphan")
    training_plans: Mapped[list["TrainingPlan"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
    )
    training_days: Mapped[list["TrainingDay"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
    )
    planned_sessions: Mapped[list["PlannedSession"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
    )
    garmin_activities: Mapped[list["GarminActivity"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
    )
    garmin_accounts: Mapped[list["GarminAccount"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
    )
    daily_health_metrics: Mapped[list["DailyHealthMetric"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
    )
    health_ai_analyses: Mapped[list["HealthAiAnalysis"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
        order_by="HealthAiAnalysis.created_at.desc()",
    )
    activity_session_matches: Mapped[list["ActivitySessionMatch"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
    )
    analysis_reports: Mapped[list["AnalysisReport"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
    )
    session_analyses: Mapped[list["SessionAnalysis"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
    )
    weekly_analyses: Mapped[list["WeeklyAnalysis"]] = relationship(
        back_populates="athlete",
        cascade="all, delete-orphan",
        order_by="WeeklyAnalysis.week_start_date.desc()",
    )
