from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.health_sync_state import HealthSyncState
from app.services.garmin.health_sync import sync_recent_health


APP_LOCAL_TIMEZONE = timezone(timedelta(hours=-3), name="America/Buenos_Aires")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_health_sync_state(db: Session, athlete_id: int, source: str = "garmin") -> HealthSyncState | None:
    return db.scalar(
        select(HealthSyncState).where(
            HealthSyncState.athlete_id == athlete_id,
            HealthSyncState.source == source,
        )
    )


def get_or_create_health_sync_state(db: Session, athlete_id: int, source: str = "garmin") -> HealthSyncState:
    state = get_health_sync_state(db, athlete_id, source)
    if state is not None:
        return state
    state = HealthSyncState(athlete_id=athlete_id, source=source, status="idle")
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def should_auto_sync_health(
    sync_state: HealthSyncState | None,
    now: datetime,
    reference_date: date,
    min_hours_between_syncs: int = 4,
) -> bool:
    if sync_state is None:
        return True
    if sync_state.status == "running":
        return False
    if sync_state.last_success_at is None:
        return True
    if sync_state.last_synced_for_date is not None and sync_state.last_synced_for_date < reference_date:
        return True

    last_success_at = _ensure_aware(sync_state.last_success_at)
    elapsed = _ensure_aware(now) - last_success_at
    if elapsed < timedelta(hours=min_hours_between_syncs):
        return False
    return reference_date == _local_datetime(now).date()


def run_health_auto_sync(
    db: Session,
    *,
    athlete_id: int,
    settings: Settings,
    reference_date: date,
    force: bool = False,
    source: str = "garmin",
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or utc_now()
    state = get_or_create_health_sync_state(db, athlete_id, source)
    if not force and not should_auto_sync_health(state, current_time, reference_date):
        return {"synced": False, "reason": "fresh", "sync_state": serialize_health_sync_state(state)}
    if state.status == "running" and not force:
        return {"synced": False, "reason": "running", "sync_state": serialize_health_sync_state(state)}

    state.status = "running"
    state.last_attempt_at = current_time
    state.error_message = None
    db.add(state)
    db.commit()
    db.refresh(state)

    try:
        result = sync_recent_health(db, settings, athlete_id=athlete_id)
    except Exception as exc:
        state.status = "failed"
        state.error_message = _controlled_error_message(exc)
        db.add(state)
        db.commit()
        db.refresh(state)
        return {
            "synced": False,
            "reason": "failed",
            "error": state.error_message,
            "sync_state": serialize_health_sync_state(state),
        }

    state.status = "success"
    state.last_success_at = current_time
    state.last_synced_for_date = reference_date
    state.records_created = result.created
    state.records_updated = result.updated
    state.error_message = "; ".join(result.errors) if result.errors else None
    db.add(state)
    db.commit()
    db.refresh(state)
    return {
        "synced": True,
        "reason": "synced",
        "records_created": result.created,
        "records_updated": result.updated,
        "days_reviewed": result.days_reviewed,
        "sync_state": serialize_health_sync_state(state),
    }


def serialize_health_sync_state(state: HealthSyncState | None) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "id": state.id,
        "athlete_id": state.athlete_id,
        "source": state.source,
        "last_attempt_at": state.last_attempt_at.isoformat() if state.last_attempt_at else None,
        "last_success_at": state.last_success_at.isoformat() if state.last_success_at else None,
        "last_synced_for_date": state.last_synced_for_date.isoformat() if state.last_synced_for_date else None,
        "status": state.status,
        "error_message": state.error_message,
        "records_created": state.records_created,
        "records_updated": state.records_updated,
    }


def build_health_sync_view(state: HealthSyncState | None, *, should_auto_sync: bool) -> dict[str, Any]:
    if state is None:
        return {
            "status": "idle",
            "label": "Datos de salud pendientes de sincronizacion",
            "detail": "Todavia no hay una sincronizacion registrada.",
            "class": "health-sync-pending",
            "should_auto_sync": should_auto_sync,
        }
    if state.status == "failed":
        return {
            "status": state.status,
            "label": "Ultima sincronizacion fallida",
            "detail": state.error_message or "Garmin no respondio correctamente.",
            "class": "health-sync-failed",
            "should_auto_sync": should_auto_sync,
        }
    if state.last_success_at:
        return {
            "status": state.status,
            "label": f"Salud sincronizada {_time_label(state.last_success_at)}",
            "detail": f"Creados {state.records_created or 0} | Actualizados {state.records_updated or 0}",
            "class": "health-sync-success",
            "should_auto_sync": should_auto_sync,
        }
    return {
        "status": state.status,
        "label": "Datos de salud pendientes de sincronizacion",
        "detail": "La sincronizacion todavia no se completo.",
        "class": "health-sync-pending",
        "should_auto_sync": should_auto_sync,
    }


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _local_datetime(value: datetime) -> datetime:
    return _ensure_aware(value).astimezone(APP_LOCAL_TIMEZONE)


def _time_label(value: datetime) -> str:
    local_value = _local_datetime(value)
    local_today = datetime.now(APP_LOCAL_TIMEZONE).date()
    if local_value.date() == local_today:
        return local_value.strftime("hoy a las %H:%M")
    return local_value.strftime("%d/%m/%Y %H:%M")


def _controlled_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return "La sincronizacion de salud Garmin fallo."
    return message[:400]
