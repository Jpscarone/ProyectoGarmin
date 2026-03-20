from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.activity_session_match import ActivitySessionMatch
    from app.db.models.analysis_report import AnalysisReport
    from app.db.models.athlete import Athlete
    from app.db.models.planned_session import PlannedSession
    from app.db.models.session_group import SessionGroup
    from app.db.models.training_plan import TrainingPlan


class TrainingDay(Base):
    __tablename__ = "training_days"
    __table_args__ = (UniqueConstraint("training_plan_id", "day_date", name="uq_training_days_plan_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id"), nullable=False, index=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    day_date: Mapped[date] = mapped_column(Date, nullable=False)
    day_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    day_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    training_plan: Mapped["TrainingPlan"] = relationship(back_populates="training_days")
    athlete: Mapped["Athlete"] = relationship(back_populates="training_days")
    planned_sessions: Mapped[list["PlannedSession"]] = relationship(
        back_populates="training_day",
        cascade="all, delete-orphan",
        order_by="PlannedSession.session_order",
    )
    session_groups: Mapped[list["SessionGroup"]] = relationship(
        back_populates="training_day",
        cascade="all, delete-orphan",
        order_by="SessionGroup.group_order",
    )
    activity_matches: Mapped[list["ActivitySessionMatch"]] = relationship(
        back_populates="training_day",
        cascade="all, delete-orphan",
    )
    analysis_reports: Mapped[list["AnalysisReport"]] = relationship(
        back_populates="training_day",
        cascade="all, delete-orphan",
    )
