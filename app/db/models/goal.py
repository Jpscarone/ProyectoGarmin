from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.athlete import Athlete
    from app.db.models.training_plan import TrainingPlan


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    training_plan_id: Mapped[int | None] = mapped_column(ForeignKey("training_plans.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sport_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete"] = relationship(back_populates="goals")
    training_plan: Mapped["TrainingPlan | None"] = relationship(back_populates="goals", foreign_keys=[training_plan_id])
