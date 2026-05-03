from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.garmin_activity import GarminActivity


class ActivityWeather(Base):
    __tablename__ = "activity_weather"
    __table_args__ = (
        UniqueConstraint("garmin_activity_id", name="uq_activity_weather_activity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garmin_activity_id: Mapped[int] = mapped_column(ForeignKey("garmin_activities.id"), nullable=False, index=True)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    weather_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    condition_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temperature_start_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    apparent_temperature_start_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_start_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    dew_point_start_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_start_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction_start_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure_start_hpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_start_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_max_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_avg_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_total_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_weather_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    activity: Mapped["GarminActivity"] = relationship(back_populates="weather")
