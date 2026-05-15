from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.athlete import Athlete


class ScheduledSyncJobLog(Base):
    __tablename__ = "scheduled_sync_job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int | None] = mapped_column(ForeignKey("athletes.id"), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    activities_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    activities_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    activities_linked: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    activity_analyses_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    health_days_synced: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    health_ai_analyses_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    weekly_analyses_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    pending_items_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    pending_items_resolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    athlete: Mapped["Athlete | None"] = relationship(back_populates="scheduled_sync_job_logs")
