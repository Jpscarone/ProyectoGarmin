from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.athlete import Athlete
from app.schemas.athlete import AthleteCreate, AthleteUpdate


def get_athletes(db: Session) -> list[Athlete]:
    statement = select(Athlete).order_by(Athlete.created_at.desc(), Athlete.id.desc())
    return list(db.scalars(statement).all())


def get_athlete(db: Session, athlete_id: int) -> Athlete | None:
    return db.get(Athlete, athlete_id)


def create_athlete(db: Session, athlete_in: AthleteCreate) -> Athlete:
    athlete = Athlete(**athlete_in.model_dump())
    db.add(athlete)
    db.commit()
    db.refresh(athlete)
    return athlete


def update_athlete(db: Session, athlete: Athlete, athlete_in: AthleteUpdate) -> Athlete:
    for field, value in athlete_in.model_dump(exclude_unset=True).items():
        setattr(athlete, field, value)

    db.add(athlete)
    db.commit()
    db.refresh(athlete)
    return athlete


def delete_athlete(db: Session, athlete: Athlete) -> None:
    db.delete(athlete)
    db.commit()
