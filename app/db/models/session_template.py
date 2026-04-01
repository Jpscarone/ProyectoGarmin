from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.session_template_step import SessionTemplateStep


class SessionTemplate(Base):
    __tablename__ = "session_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sport_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    discipline_variant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_hr_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_pace_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_power_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_rpe_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    steps: Mapped[list["SessionTemplateStep"]] = relationship(
        back_populates="session_template",
        cascade="all, delete-orphan",
        order_by="SessionTemplateStep.step_order",
    )
