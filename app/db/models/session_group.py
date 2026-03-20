from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.analysis_report import AnalysisReport
    from app.db.models.planned_session import PlannedSession
    from app.db.models.training_day import TrainingDay


class SessionGroup(Base):
    __tablename__ = "session_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_day_id: Mapped[int] = mapped_column(ForeignKey("training_days.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    group_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    training_day: Mapped["TrainingDay"] = relationship(back_populates="session_groups")
    planned_sessions: Mapped[list["PlannedSession"]] = relationship(
        back_populates="session_group",
        order_by="PlannedSession.session_order",
    )
    analysis_reports: Mapped[list["AnalysisReport"]] = relationship(
        back_populates="session_group",
        cascade="all, delete-orphan",
    )
