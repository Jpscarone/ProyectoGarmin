from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.athlete import Athlete
from app.schemas.athlete import AthleteCreate, AthleteUpdate


ATHLETE_STATUS_ACTIVE = "active"
ATHLETE_STATUS_INACTIVE = "inactive"
ATHLETE_STATUS_ARCHIVED = "archived"
ATHLETE_STATUSES = {ATHLETE_STATUS_ACTIVE, ATHLETE_STATUS_INACTIVE, ATHLETE_STATUS_ARCHIVED}


def normalize_athlete_status(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in ATHLETE_STATUSES:
        return normalized
    return ATHLETE_STATUS_ACTIVE


def get_athletes(db: Session) -> list[Athlete]:
    statement = select(Athlete).order_by(Athlete.created_at.desc(), Athlete.id.desc())
    return list(db.scalars(statement).all())


def get_active_athletes(db: Session) -> list[Athlete]:
    statement = (
        select(Athlete)
        .where(Athlete.status == ATHLETE_STATUS_ACTIVE)
        .order_by(Athlete.name.asc(), Athlete.id.asc())
    )
    return list(db.scalars(statement).all())


def get_athlete(db: Session, athlete_id: int) -> Athlete | None:
    return db.get(Athlete, athlete_id)


def create_athlete(db: Session, athlete_in: AthleteCreate) -> Athlete:
    payload = athlete_in.model_dump()
    payload["status"] = normalize_athlete_status(payload.get("status"))
    athlete = Athlete(**payload)
    db.add(athlete)
    db.commit()
    db.refresh(athlete)
    return athlete


def update_athlete(db: Session, athlete: Athlete, athlete_in: AthleteUpdate) -> Athlete:
    data = athlete_in.model_dump(exclude_unset=True)
    if "status" in data:
        data["status"] = normalize_athlete_status(data.get("status"))
    for field, value in data.items():
        setattr(athlete, field, value)

    db.add(athlete)
    db.commit()
    db.refresh(athlete)
    return athlete


def delete_athlete(db: Session, athlete: Athlete) -> None:
    db.delete(athlete)
    db.commit()
