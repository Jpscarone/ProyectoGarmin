from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.activity_session_match import ActivitySessionMatch
    from app.db.models.activity_weather import ActivityWeather
    from app.db.models.analysis_report import AnalysisReport
    from app.db.models.athlete import Athlete
    from app.db.models.garmin_activity_lap import GarminActivityLap
    from app.db.models.session_analysis import SessionAnalysis


class GarminActivity(Base):
    __tablename__ = "garmin_activities"
    __table_args__ = (
        Index("ix_garmin_activities_athlete_start_time", "athlete_id", "start_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    garmin_activity_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    activity_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sport_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discipline_variant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_multisport: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moving_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_pace_sec_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_effect_aerobic: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_effect_anaerobic: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete"] = relationship(back_populates="garmin_activities")
    laps: Mapped[list["GarminActivityLap"]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        order_by="GarminActivityLap.lap_number",
    )
    weather: Mapped["ActivityWeather | None"] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        uselist=False,
    )
    activity_match: Mapped["ActivitySessionMatch | None"] = relationship(
        back_populates="garmin_activity",
        cascade="all, delete-orphan",
        uselist=False,
    )
    analysis_reports: Mapped[list["AnalysisReport"]] = relationship(
        back_populates="garmin_activity",
        cascade="all, delete-orphan",
    )
    session_analyses: Mapped[list["SessionAnalysis"]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
    )
