from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.athlete import Athlete
    from app.db.models.user import User


class UserAthletePermission(Base):
    __tablename__ = "user_athlete_permissions"
    __table_args__ = (UniqueConstraint("user_id", "athlete_id", name="uq_user_athlete_permission_user_athlete"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), nullable=False, index=True)
    permission_role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer", server_default="viewer")
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    can_sync_garmin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="athlete_permissions")
    athlete: Mapped["Athlete"] = relationship(back_populates="user_permissions")
