from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.planned_session import PlannedSession


class PlannedSessionStep(Base):
    __tablename__ = "planned_session_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planned_session_id: Mapped[int] = mapped_column(ForeignKey("planned_sessions.id"), nullable=False, index=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    repeat_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_hr_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_hr_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_power_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_power_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_pace_min_sec_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_pace_max_sec_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_cadence_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_cadence_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    planned_session: Mapped["PlannedSession"] = relationship(back_populates="planned_session_steps")
