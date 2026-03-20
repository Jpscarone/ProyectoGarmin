from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.analysis_report_item import AnalysisReportItem
    from app.db.models.athlete import Athlete
    from app.db.models.garmin_activity import GarminActivity
    from app.db.models.planned_session import PlannedSession
    from app.db.models.session_group import SessionGroup
    from app.db.models.training_day import TrainingDay


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    training_day_id: Mapped[int | None] = mapped_column(ForeignKey("training_days.id"), nullable=True, index=True)
    session_group_id: Mapped[int | None] = mapped_column(ForeignKey("session_groups.id"), nullable=True, index=True)
    planned_session_id: Mapped[int | None] = mapped_column(ForeignKey("planned_sessions.id"), nullable=True, index=True)
    garmin_activity_id_fk: Mapped[int | None] = mapped_column(ForeignKey("garmin_activities.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_status: Mapped[str] = mapped_column(String(50), nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_conclusion_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete"] = relationship(back_populates="analysis_reports")
    training_day: Mapped["TrainingDay | None"] = relationship(back_populates="analysis_reports")
    session_group: Mapped["SessionGroup | None"] = relationship(back_populates="analysis_reports")
    planned_session: Mapped["PlannedSession | None"] = relationship(back_populates="analysis_reports")
    garmin_activity: Mapped["GarminActivity | None"] = relationship(back_populates="analysis_reports")
    items: Mapped[list["AnalysisReportItem"]] = relationship(
        back_populates="analysis_report",
        cascade="all, delete-orphan",
        order_by="AnalysisReportItem.item_order",
    )
