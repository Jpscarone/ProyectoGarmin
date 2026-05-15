from __future__ import annotations

from dataclasses import dataclass
import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.athlete import Athlete
from app.db.models.user import User
from app.db.models.user_athlete_permission import UserAthletePermission


ROLE_ADMIN = "admin"
ROLE_COACH = "coach"
ROLE_ATHLETE = "athlete"
USER_ROLES = {ROLE_ADMIN, ROLE_COACH, ROLE_ATHLETE}
PERMISSION_OWNER = "owner"
PERMISSION_COACH = "coach"
PERMISSION_VIEWER = "viewer"


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EffectiveAthletePermission:
    athlete_id: int
    permission_role: str
    can_view: bool
    can_edit: bool
    can_sync_garmin: bool


def normalize_user_role(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in USER_ROLES else ROLE_ATHLETE


def normalize_permission_role(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {PERMISSION_OWNER, PERMISSION_COACH, PERMISSION_VIEWER}:
        return normalized
    return PERMISSION_VIEWER


def default_permission_flags(permission_role: str) -> dict[str, bool]:
    normalized = normalize_permission_role(permission_role)
    if normalized in {PERMISSION_OWNER, PERMISSION_COACH}:
        return {"can_view": True, "can_edit": True, "can_sync_garmin": True}
    return {"can_view": True, "can_edit": False, "can_sync_garmin": False}


def list_accessible_athletes(db: Session, user: User, *, only_active: bool = False) -> list[Athlete]:
    statement = select(Athlete)
    if only_active:
        statement = statement.where(Athlete.status == "active")
    if user.role == ROLE_ADMIN:
        return list(db.scalars(statement.order_by(Athlete.name.asc(), Athlete.id.asc())).all())

    permission_subquery = (
        select(UserAthletePermission.athlete_id)
        .where(
            UserAthletePermission.user_id == user.id,
            UserAthletePermission.can_view.is_(True),
        )
    )
    return list(
        db.scalars(
            statement.where(Athlete.id.in_(permission_subquery)).order_by(Athlete.name.asc(), Athlete.id.asc())
        ).all()
    )


def get_permission_for_athlete(db: Session, user: User, athlete_id: int) -> EffectiveAthletePermission | None:
    if user.role == ROLE_ADMIN:
        return EffectiveAthletePermission(
            athlete_id=athlete_id,
            permission_role=PERMISSION_OWNER,
            can_view=True,
            can_edit=True,
            can_sync_garmin=True,
        )
    permission = db.scalar(
        select(UserAthletePermission).where(
            UserAthletePermission.user_id == user.id,
            UserAthletePermission.athlete_id == athlete_id,
        )
    )
    if permission is None:
        return None
    permission_role = normalize_permission_role(permission.permission_role)
    defaults = default_permission_flags(permission_role)
    return EffectiveAthletePermission(
        athlete_id=athlete_id,
        permission_role=permission_role,
        can_view=bool(permission.can_view),
        can_edit=bool(permission.can_edit or defaults["can_edit"]),
        can_sync_garmin=bool(permission.can_sync_garmin or defaults["can_sync_garmin"]),
    )


def require_permission_for_athlete(
    db: Session,
    user: User,
    athlete_id: int,
    *,
    can_edit: bool = False,
    can_sync_garmin: bool = False,
) -> EffectiveAthletePermission:
    permission = get_permission_for_athlete(db, user, athlete_id)
    if permission is None or not permission.can_view:
        logger.warning("Unauthorized athlete access blocked user_id=%s role=%s athlete_id=%s", user.id, user.role, athlete_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para acceder a este atleta.")
    if can_edit and not permission.can_edit:
        logger.warning("Unauthorized athlete edit blocked user_id=%s role=%s athlete_id=%s", user.id, user.role, athlete_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso de edición sobre este atleta.")
    if can_sync_garmin and not permission.can_sync_garmin:
        logger.warning("Unauthorized Garmin sync blocked user_id=%s role=%s athlete_id=%s", user.id, user.role, athlete_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para sincronizar Garmin en este atleta.")
    return permission


def require_can_view_athlete(db: Session, user: User, athlete_id: int) -> EffectiveAthletePermission:
    return require_permission_for_athlete(db, user, athlete_id)


def require_can_edit_athlete(db: Session, user: User, athlete_id: int) -> EffectiveAthletePermission:
    return require_permission_for_athlete(db, user, athlete_id, can_edit=True)


def require_can_sync_garmin(db: Session, user: User, athlete_id: int) -> EffectiveAthletePermission:
    return require_permission_for_athlete(db, user, athlete_id, can_sync_garmin=True)
