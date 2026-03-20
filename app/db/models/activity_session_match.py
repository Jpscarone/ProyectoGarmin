from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.athlete import Athlete
    from app.db.models.garmin_activity import GarminActivity
    from app.db.models.planned_session import PlannedSession
    from app.db.models.training_day import TrainingDay


class ActivitySessionMatch(Base):
    __tablename__ = "activity_session_matches"
    __table_args__ = (
        UniqueConstraint("garmin_activity_id_fk", name="uq_activity_session_match_activity"),
        UniqueConstraint("planned_session_id_fk", name="uq_activity_session_match_planned_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    garmin_activity_id_fk: Mapped[int] = mapped_column(ForeignKey("garmin_activities.id"), nullable=False, index=True)
    planned_session_id_fk: Mapped[int] = mapped_column(ForeignKey("planned_sessions.id"), nullable=False, index=True)
    training_day_id_fk: Mapped[int] = mapped_column(ForeignKey("training_days.id"), nullable=False, index=True)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_method: Mapped[str] = mapped_column(String(50), nullable=False)
    match_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete"] = relationship(back_populates="activity_session_matches")
    garmin_activity: Mapped["GarminActivity"] = relationship(back_populates="activity_match")
    planned_session: Mapped["PlannedSession"] = relationship(back_populates="activity_match")
    training_day: Mapped["TrainingDay"] = relationship(back_populates="activity_matches")
