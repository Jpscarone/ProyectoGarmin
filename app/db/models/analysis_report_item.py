from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.analysis_report import AnalysisReport


class AnalysisReportItem(Base):
    __tablename__ = "analysis_report_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_report_id: Mapped[int] = mapped_column(ForeignKey("analysis_reports.id"), nullable=False, index=True)
    item_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    planned_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    item_status: Mapped[str] = mapped_column(String(50), nullable=False)
    comment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    analysis_report: Mapped["AnalysisReport"] = relationship(back_populates="items")
