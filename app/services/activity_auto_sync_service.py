from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.athlete import Athlete
from app.db.models.garmin_account import GarminAccount
from app.db.models.garmin_activity import GarminActivity
from app.services.garmin.activity_sync import GarminSyncResult, sync_activities_by_date


APP_LOCAL_TIMEZONE = timezone(timedelta(hours=-3), name="America/Buenos_Aires")
AUTO_ACTIVITY_SYNC_DAYS = 30
AUTO_ACTIVITY_SYNC_COOLDOWN_MINUTES = 60


@dataclass
class ActivityAutoSyncDecision:
    should_sync: bool
    reason: str
    start_date: date | None
    end_date: date


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_latest_activity_for_athlete(db: Session, athlete_id: int) -> GarminActivity | None:
    return db.scalar(
        select(GarminActivity)
        .where(GarminActivity.athlete_id == athlete_id)
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .limit(1)
    )


def get_garmin_account_for_athlete(db: Session, athlete_id: int) -> GarminAccount | None:
    return db.scalar(
        select(GarminAccount)
        .where(GarminAccount.athlete_id == athlete_id)
        .order_by(GarminAccount.id.asc())
        .limit(1)
    )


def get_or_create_garmin_account_for_athlete(db: Session, athlete: Athlete) -> GarminAccount:
    existing = get_garmin_account_for_athlete(db, athlete.id)
    if existing is not None:
        return existing
    account = GarminAccount(athlete_id=athlete.id, status="active")
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def should_auto_sync_activities(
    account: GarminAccount | None,
    latest_activity: GarminActivity | None,
    *,
    now: datetime,
    force: bool = False,
    cooldown_minutes: int = AUTO_ACTIVITY_SYNC_COOLDOWN_MINUTES,
) -> ActivityAutoSyncDecision:
    local_today = _local_datetime(now).date()
    start_date = (
        activity_local_date(latest_activity.start_time)
        if latest_activity is not None and latest_activity.start_time is not None
        else local_today - timedelta(days=AUTO_ACTIVITY_SYNC_DAYS)
    )

    if force:
        return ActivityAutoSyncDecision(True, "force", start_date, local_today)

    if latest_activity is not None and latest_activity.start_time is not None and start_date == local_today:
        return ActivityAutoSyncDecision(False, "already_today", start_date, local_today)

    if account is not None and account.last_activity_sync_at is not None:
        elapsed = _ensure_aware(now) - _ensure_aware(account.last_activity_sync_at)
        if elapsed < timedelta(minutes=cooldown_minutes):
            return ActivityAutoSyncDecision(False, "cooldown", start_date, local_today)

    return ActivityAutoSyncDecision(True, "stale", start_date, local_today)


def run_activity_auto_sync(
    db: Session,
    *,
    athlete: Athlete,
    settings: Settings,
    force: bool = False,
    mfa_code: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or utc_now()
    account = get_or_create_garmin_account_for_athlete(db, athlete)
    latest_activity = get_latest_activity_for_athlete(db, athlete.id)
    decision = should_auto_sync_activities(account, latest_activity, now=current_time, force=force)

    if not decision.should_sync:
        message = _skip_message(decision.reason)
        account.last_activity_sync_status = "skipped"
        account.last_activity_sync_message = message
        account.last_activity_sync_start_date = decision.start_date
        account.last_activity_sync_end_date = decision.end_date
        db.add(account)
        db.commit()
        db.refresh(account)
        return {
            "synced": False,
            "reason": decision.reason,
            "message": message,
            "sync_result": None,
            "state": serialize_activity_sync_state(account),
        }

    account.last_activity_sync_at = current_time
    account.last_activity_sync_status = "running"
    account.last_activity_sync_message = None
    account.last_activity_sync_start_date = decision.start_date
    account.last_activity_sync_end_date = decision.end_date
    db.add(account)
    db.commit()
    db.refresh(account)

    try:
        result = sync_activities_by_date(
            db,
            settings,
            start_date=decision.start_date or decision.end_date,
            end_date=decision.end_date,
            mfa_code=mfa_code,
            athlete_id=athlete.id,
        )
    except Exception as exc:
        account.last_activity_sync_status = "error"
        account.last_activity_sync_message = f"Error al sincronizar: {_controlled_error_message(exc)}"
        db.add(account)
        db.commit()
        db.refresh(account)
        return {
            "synced": False,
            "reason": "error",
            "message": account.last_activity_sync_message,
            "sync_result": None,
            "state": serialize_activity_sync_state(account),
        }

    message = _success_message(result)
    if result.errors:
        message = f"{message} Errores: {'; '.join(result.errors[:3])}"
    account.last_activity_sync_status = "success"
    account.last_activity_sync_message = message
    account.last_activity_sync_start_date = decision.start_date
    account.last_activity_sync_end_date = decision.end_date
    db.add(account)
    db.commit()
    db.refresh(account)
    return {
        "synced": True,
        "reason": "synced",
        "message": message,
        "sync_result": result,
        "state": serialize_activity_sync_state(account),
    }


def serialize_activity_sync_state(account: GarminAccount | None) -> dict[str, Any] | None:
    if account is None:
        return None
    return {
        "garmin_account_id": account.id,
        "athlete_id": account.athlete_id,
        "last_activity_sync_at": account.last_activity_sync_at.isoformat() if account.last_activity_sync_at else None,
        "last_activity_sync_status": account.last_activity_sync_status,
        "last_activity_sync_message": account.last_activity_sync_message,
        "last_activity_sync_start_date": account.last_activity_sync_start_date.isoformat() if account.last_activity_sync_start_date else None,
        "last_activity_sync_end_date": account.last_activity_sync_end_date.isoformat() if account.last_activity_sync_end_date else None,
    }


def activity_local_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    return _local_datetime(value).date()


def _success_message(result: GarminSyncResult) -> str:
    return (
        "Sincronizacion automatica realizada. "
        f"Se encontraron {result.inserted} actividades nuevas / {result.existing} actualizadas."
    )


def _skip_message(reason: str) -> str:
    if reason == "already_today":
        return "No se sincronizo porque la ultima actividad ya es de hoy."
    if reason == "cooldown":
        return "No se sincronizo porque ya se intento hace menos de 60 minutos."
    return "No se realizo la sincronizacion automatica."


def _controlled_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return "Garmin no respondio correctamente."
    return message[:400]


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _local_datetime(value: datetime) -> datetime:
    return _ensure_aware(value).astimezone(APP_LOCAL_TIMEZONE)
