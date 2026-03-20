from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionGroupBase(BaseModel):
    training_day_id: int
    name: str
    group_type: str | None = None
    group_order: int = 1
    notes: str | None = None


class SessionGroupCreate(SessionGroupBase):
    pass


class SessionGroupUpdate(BaseModel):
    training_day_id: int | None = None
    name: str | None = None
    group_type: str | None = None
    group_order: int | None = None
    notes: str | None = None


class SessionGroupRead(SessionGroupBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
