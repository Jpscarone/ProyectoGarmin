from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.analysis_report import AnalysisReport
    from app.db.models.athlete import Athlete
    from app.db.models.garmin_activity import GarminActivity
    from app.db.models.planned_session import PlannedSession


class PendingTrainingItem(Base):
    __tablename__ = "pending_training_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending", index=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", server_default="medium")
    reference_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    garmin_activity_id: Mapped[int | None] = mapped_column(ForeignKey("garmin_activities.id"), nullable=True, index=True)
    planned_session_id: Mapped[int | None] = mapped_column(ForeignKey("planned_sessions.id"), nullable=True, index=True)
    analysis_report_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_reports.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete"] = relationship(back_populates="pending_training_items")
    garmin_activity: Mapped["GarminActivity | None"] = relationship()
    planned_session: Mapped["PlannedSession | None"] = relationship()
    analysis_report: Mapped["AnalysisReport | None"] = relationship()
