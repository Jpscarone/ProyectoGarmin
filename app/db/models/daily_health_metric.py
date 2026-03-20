from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.athlete import Athlete


class DailyHealthMetric(Base):
    __tablename__ = "daily_health_metrics"
    __table_args__ = (
        UniqueConstraint("athlete_id", "metric_date", name="uq_daily_health_metric_athlete_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    sleep_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deep_sleep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rem_sleep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awake_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress_avg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    high_stress_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hrv_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hrv_avg_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_daily_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovery_time_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    spo2_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    respiration_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_health_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete"] = relationship(back_populates="daily_health_metrics")
