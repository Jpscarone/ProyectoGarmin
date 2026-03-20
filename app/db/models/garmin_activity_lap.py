from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.garmin_activity import GarminActivity


class GarminActivityLap(Base):
    __tablename__ = "garmin_activity_laps"
    __table_args__ = (
        UniqueConstraint("garmin_activity_id_fk", "lap_number", name="uq_garmin_activity_lap_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garmin_activity_id_fk: Mapped[int] = mapped_column(ForeignKey("garmin_activities.id"), nullable=False, index=True)
    lap_number: Mapped[int] = mapped_column(Integer, nullable=False)
    lap_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moving_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_pace_sec_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    stroke_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    swolf: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_lap_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    activity: Mapped["GarminActivity"] = relationship(back_populates="laps")
