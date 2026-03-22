from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.athlete import Athlete
    from app.db.models.goal import Goal
    from app.db.models.training_day import TrainingDay


class TrainingPlan(Base):
    __tablename__ = "training_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sport_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete"] = relationship(back_populates="training_plans")
    goal: Mapped["Goal | None"] = relationship(foreign_keys=[goal_id])
    goals: Mapped[list["Goal"]] = relationship(
        back_populates="training_plan",
        foreign_keys="Goal.training_plan_id",
        order_by="Goal.event_date",
        cascade="all, delete-orphan",
    )
    training_days: Mapped[list["TrainingDay"]] = relationship(
        back_populates="training_plan",
        cascade="all, delete-orphan",
        order_by="TrainingDay.day_date",
    )
