from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.activity_auto_sync_service import (
    activity_local_date,
    get_garmin_account_for_athlete,
    get_latest_activity_for_athlete,
    get_or_create_garmin_account_for_athlete,
)
from app.services.analysis_v2.session_analysis_service import run_session_analysis
from app.services.garmin.activity_sync import sync_activities_by_date
from app.services.health_auto_sync_service import get_health_sync_state, run_health_auto_sync
from app.services.session_match_service import auto_match_activity, preview_activity_match


logger = logging.getLogger(__name__)

APP_LOCAL_TIMEZONE = timezone(timedelta(hours=-3), name="America/Buenos_Aires")
ACTIVITY_REFRESH_COOLDOWN_MINUTES = 15
HEALTH_REFRESH_COOLDOWN_HOURS = 6
AUTO_LINK_SAFE_SCORE = 85.0


def run_dashboard_auto_refresh(
    db: Session,
    athlete,
    training_plan: TrainingPlan | None,
    selected_date: date,
) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    target_date = min(selected_date, _local_date(now))

    steps: list[dict[str, str]] = []
    errors: list[str] = []
    updated = False

    try:
        health_result = _run_health_refresh_step(
            db,
            athlete_id=athlete.id,
            selected_date=selected_date,
            target_date=target_date,
            settings=settings,
            now=now,
        )
        steps.append(health_result["step"])
        updated = updated or health_result["updated"]
        errors.extend(health_result["errors"])
    except Exception as exc:
        logger.exception("Dashboard auto-refresh health step failed athlete_id=%s", athlete.id)
        message = _controlled_error_message(exc)
        steps.append(_build_step("health_sync", "failed", f"Salud: {message}"))
        errors.append(message)

    try:
        activity_result = _run_activity_refresh_step(
            db,
            athlete=athlete,
            training_plan=training_plan,
            selected_date=selected_date,
            target_date=target_date,
            settings=settings,
            now=now,
        )
        steps.append(activity_result["step"])
        updated = updated or activity_result["updated"]
        errors.extend(activity_result["errors"])
    except Exception as exc:
        logger.exception("Dashboard auto-refresh activity step failed athlete_id=%s", athlete.id)
        message = _controlled_error_message(exc)
        steps.append(_build_step("activity_sync", "failed", f"Actividades: {message}"))
        errors.append(message)

    try:
        match_result = _run_linking_step(
            db,
            athlete_id=athlete.id,
            training_plan=training_plan,
            selected_date=selected_date,
            target_date=target_date,
        )
        steps.append(match_result["step"])
        updated = updated or match_result["updated"]
        errors.extend(match_result["errors"])
    except Exception as exc:
        logger.exception("Dashboard auto-refresh linking step failed athlete_id=%s", athlete.id)
        message = _controlled_error_message(exc)
        steps.append(_build_step("activity_linking", "failed", f"Vinculación: {message}"))
        errors.append(message)

    try:
        analysis_result = _run_session_analysis_step(
            db,
            athlete_id=athlete.id,
            training_plan=training_plan,
            selected_date=selected_date,
            target_date=target_date,
        )
        steps.append(analysis_result["step"])
        updated = updated or analysis_result["updated"]
        errors.extend(analysis_result["errors"])
    except Exception as exc:
        logger.exception("Dashboard auto-refresh analysis step failed athlete_id=%s", athlete.id)
        message = _controlled_error_message(exc)
        steps.append(_build_step("session_analysis", "failed", f"Análisis: {message}"))
        errors.append(message)

    ok = not any(step["status"] == "failed" for step in steps)
    return {
        "ok": ok,
        "updated": updated,
        "steps": steps,
        "errors": errors,
    }


def build_dashboard_refresh_status(refresh_result: dict[str, Any]) -> dict[str, Any]:
    steps = refresh_result.get("steps") or []
    any_failed = any(step.get("status") == "failed" for step in steps)
    any_done = any(step.get("status") == "done" for step in steps)
    if any_failed and any_done:
        return {
            "phase": "warning",
            "message": "Datos parcialmente actualizados. Garmin no respondió en una parte.",
            "steps": steps,
        }
    if any_failed:
        return {
            "phase": "error",
            "message": "No se pudo actualizar automáticamente. Se muestran los últimos datos disponibles.",
            "steps": steps,
        }
    if any_done:
        return {
            "phase": "success",
            "message": "Datos actualizados.",
            "steps": steps,
        }
    return {
        "phase": "success",
        "message": "Datos al día. No hizo falta actualizar ahora.",
        "steps": steps,
    }


def initial_dashboard_refresh_status() -> dict[str, Any]:
    return {
        "phase": "loading",
        "message": "Actualizando datos del atleta...",
        "steps": [
            _build_step("health_sync", "pending", "Salud"),
            _build_step("activity_sync", "pending", "Actividades"),
            _build_step("activity_linking", "pending", "Vinculación"),
            _build_step("session_analysis", "pending", "Análisis"),
        ],
    }


def _run_health_refresh_step(
    db: Session,
    *,
    athlete_id: int,
    selected_date: date,
    target_date: date,
    settings,
    now: datetime,
) -> dict[str, Any]:
    if selected_date > _local_date(now):
        return {"step": _build_step("health_sync", "skipped", "Salud: fecha futura, sin sincronización."), "updated": False, "errors": []}

    metric = _get_health_metric_for_date(db, athlete_id, target_date)
    state = get_health_sync_state(db, athlete_id)
    due, reason = _should_refresh_health(metric, state, selected_date=selected_date, target_date=target_date, now=now)
    if not due:
        return {"step": _build_step("health_sync", "skipped", f"Salud: {reason}"), "updated": False, "errors": []}

    result = run_health_auto_sync(
        db,
        athlete_id=athlete_id,
        settings=settings,
        reference_date=target_date,
        force=True,
        now=now,
    )
    if result.get("synced"):
        created = result.get("records_created", 0)
        updated_count = result.get("records_updated", 0)
        return {
            "step": _build_step("health_sync", "done", f"Salud sincronizada. Creados {created}, actualizados {updated_count}."),
            "updated": True,
            "errors": [],
        }
    error_message = result.get("error") or "No se pudo sincronizar salud."
    return {
        "step": _build_step("health_sync", "failed", f"Salud: {error_message}"),
        "updated": False,
        "errors": [str(error_message)],
    }


def _run_activity_refresh_step(
    db: Session,
    *,
    athlete,
    training_plan: TrainingPlan | None,
    selected_date: date,
    target_date: date,
    settings,
    now: datetime,
) -> dict[str, Any]:
    if selected_date > _local_date(now):
        return {"step": _build_step("activity_sync", "skipped", "Actividades: fecha futura, sin sincronización."), "updated": False, "errors": []}

    latest_activity = get_latest_activity_for_athlete(db, athlete.id)
    account = get_or_create_garmin_account_for_athlete(db, athlete)
    today_session = _get_first_session_for_date(db, athlete.id, training_plan, target_date)
    activities = _get_activities_for_date(db, athlete.id, target_date)
    linked_to_today_session = any(
        activity.activity_match is not None and today_session is not None and activity.activity_match.planned_session_id_fk == today_session.id
        for activity in activities
    )
    due, reason, start_date = _should_refresh_activities(
        account=account,
        latest_activity=latest_activity,
        selected_date=selected_date,
        target_date=target_date,
        has_session=today_session is not None,
        has_activities=bool(activities),
        has_linked_activity=linked_to_today_session,
        now=now,
    )
    if not due:
        return {"step": _build_step("activity_sync", "skipped", f"Actividades: {reason}"), "updated": False, "errors": []}

    account.last_activity_sync_at = now
    account.last_activity_sync_status = "running"
    account.last_activity_sync_message = None
    account.last_activity_sync_start_date = start_date
    account.last_activity_sync_end_date = target_date
    db.add(account)
    db.commit()

    try:
        result = sync_activities_by_date(
            db,
            settings,
            start_date=start_date,
            end_date=target_date,
            athlete_id=athlete.id,
        )
    except Exception as exc:
        logger.exception("Dashboard auto-refresh Garmin activities failed athlete_id=%s", athlete.id)
        account.last_activity_sync_status = "error"
        account.last_activity_sync_message = _controlled_error_message(exc)
        db.add(account)
        db.commit()
        return {
            "step": _build_step("activity_sync", "failed", f"Actividades: {account.last_activity_sync_message}"),
            "updated": False,
            "errors": [account.last_activity_sync_message],
        }

    account.last_activity_sync_status = "success"
    account.last_activity_sync_message = (
        f"Se sincronizaron {result.inserted} nuevas y {result.existing} actualizadas."
    )
    db.add(account)
    db.commit()
    return {
        "step": _build_step("activity_sync", "done", f"Actividades: {account.last_activity_sync_message}"),
        "updated": bool(result.inserted or result.existing),
        "errors": list(result.errors or []),
    }


def _run_linking_step(
    db: Session,
    *,
    athlete_id: int,
    training_plan: TrainingPlan | None,
    selected_date: date,
    target_date: date,
) -> dict[str, Any]:
    if selected_date > datetime.now(APP_LOCAL_TIMEZONE).date():
        return {"step": _build_step("activity_linking", "skipped", "Vinculación: fecha futura, sin acción."), "updated": False, "errors": []}

    session = _get_first_session_for_date(db, athlete_id, training_plan, target_date)
    if session is None:
        return {"step": _build_step("activity_linking", "skipped", "Vinculación: sin sesión planificada para esa fecha."), "updated": False, "errors": []}

    activities = [activity for activity in _get_activities_for_date(db, athlete_id, target_date) if activity.activity_match is None]
    if not activities:
        return {"step": _build_step("activity_linking", "skipped", "Vinculación: no hay actividades candidatas sin vincular."), "updated": False, "errors": []}

    matched = 0
    candidate = 0
    ambiguous = 0
    errors: list[str] = []

    for activity in activities:
        decision = preview_activity_match(db, activity.id, training_plan_id=training_plan.id if training_plan else None)
        if decision.status == "matched" and decision.matched_session_id and (decision.score or 0.0) >= AUTO_LINK_SAFE_SCORE:
            auto_match_activity(db, activity.id, training_plan_id=training_plan.id if training_plan else None)
            matched += 1
        elif decision.status == "ambiguous":
            ambiguous += 1
        elif decision.status == "candidate":
            candidate += 1

    if matched:
        detail = f"Vinculación: {matched} actividad(es) vinculadas automáticamente."
        if ambiguous or candidate:
            detail += f" {ambiguous + candidate} quedaron para revisión manual."
        return {"step": _build_step("activity_linking", "done", detail), "updated": True, "errors": errors}
    if ambiguous or candidate:
        return {
            "step": _build_step("activity_linking", "skipped", "Vinculación: hay candidatas, pero no se auto-vincularon por ambigüedad o score insuficiente."),
            "updated": False,
            "errors": errors,
        }
    return {"step": _build_step("activity_linking", "skipped", "Vinculación: no hubo matches seguros para auto-vincular."), "updated": False, "errors": errors}


def _run_session_analysis_step(
    db: Session,
    *,
    athlete_id: int,
    training_plan: TrainingPlan | None,
    selected_date: date,
    target_date: date,
) -> dict[str, Any]:
    if selected_date > datetime.now(APP_LOCAL_TIMEZONE).date():
        return {"step": _build_step("session_analysis", "skipped", "Análisis: fecha futura, sin acción."), "updated": False, "errors": []}

    activities = _get_activities_for_date(db, athlete_id, target_date)
    pending_pairs: list[tuple[int, int]] = []
    for activity in activities:
        if activity.activity_match is None or activity.activity_match.planned_session is None:
            continue
        planned_session = activity.activity_match.planned_session
        if planned_session.athlete_id != athlete_id:
            continue
        if training_plan is not None:
            training_day = planned_session.training_day
            if training_day is None or training_day.training_plan_id != training_plan.id:
                continue
        if not _has_completed_analysis(activity, planned_session.id):
            pending_pairs.append((planned_session.id, activity.id))

    if not pending_pairs:
        return {"step": _build_step("session_analysis", "skipped", "Análisis: no hay sesiones vinculadas pendientes."), "updated": False, "errors": []}

    analyzed = 0
    errors: list[str] = []
    for planned_session_id, activity_id in pending_pairs:
        try:
            run_session_analysis(
                db,
                planned_session_id=planned_session_id,
                activity_id=activity_id,
                trigger_source="dashboard_auto_refresh",
            )
            analyzed += 1
        except Exception as exc:
            logger.exception(
                "Dashboard auto-refresh analysis failed athlete_id=%s planned_session_id=%s activity_id=%s",
                athlete_id,
                planned_session_id,
                activity_id,
            )
            errors.append(_controlled_error_message(exc))

    if analyzed and not errors:
        return {
            "step": _build_step("session_analysis", "done", f"Análisis: {analyzed} análisis automáticos completados."),
            "updated": True,
            "errors": [],
        }
    if analyzed:
        return {
            "step": _build_step("session_analysis", "failed", f"Análisis: {analyzed} completados, pero hubo errores parciales."),
            "updated": True,
            "errors": errors,
        }
    return {
        "step": _build_step("session_analysis", "failed", "Análisis: no se pudo ejecutar el análisis automático."),
        "updated": False,
        "errors": errors,
    }


def _should_refresh_health(
    metric: DailyHealthMetric | None,
    state,
    *,
    selected_date: date,
    target_date: date,
    now: datetime,
) -> tuple[bool, str]:
    local_today = _local_date(now)
    if selected_date > local_today:
        return False, "fecha futura"
    if target_date < local_today:
        if metric is not None:
            return False, "fecha pasada con datos ya guardados"
        return False, "fecha pasada sin soporte de auto-sync puntual"
    if state is not None and state.status == "running":
        return False, "ya hay una sincronización de salud en curso"
    if metric is None:
        if state is not None and state.last_attempt_at is not None and _elapsed_since(state.last_attempt_at, now) < timedelta(hours=HEALTH_REFRESH_COOLDOWN_HOURS):
            return False, "ya se intentó sincronizar salud hace poco"
        return True, "faltan datos de salud de hoy"
    if metric.updated_at is not None and _elapsed_since(metric.updated_at, now) >= timedelta(hours=HEALTH_REFRESH_COOLDOWN_HOURS):
        return True, "datos de salud desactualizados"
    return False, "salud ya actualizada recientemente"


def _should_refresh_activities(
    *,
    account,
    latest_activity: GarminActivity | None,
    selected_date: date,
    target_date: date,
    has_session: bool,
    has_activities: bool,
    has_linked_activity: bool,
    now: datetime,
) -> tuple[bool, str, date]:
    local_today = _local_date(now)
    start_date = activity_local_date(latest_activity.start_time) if latest_activity and latest_activity.start_time else (target_date - timedelta(days=30))
    if selected_date > local_today:
        return False, "fecha futura", start_date
    if account is not None and account.last_activity_sync_at is not None and _elapsed_since(account.last_activity_sync_at, now) < timedelta(minutes=ACTIVITY_REFRESH_COOLDOWN_MINUTES):
        return False, "ya se intentó sincronizar actividades hace poco", start_date
    latest_date = activity_local_date(latest_activity.start_time) if latest_activity and latest_activity.start_time else None
    if latest_date is None:
        return True, "no hay actividades previas", target_date - timedelta(days=30)
    if target_date == local_today and latest_date < target_date:
        return True, "la última actividad sincronizada es anterior a hoy", latest_date
    if has_session and not has_linked_activity:
        return True, "hay sesión sin actividad vinculada", min(latest_date, target_date)
    if has_session and not has_activities:
        return True, "hay sesión planificada sin actividades del día", min(latest_date, target_date)
    return False, "actividades ya actualizadas", start_date


def _get_health_metric_for_date(db: Session, athlete_id: int, reference_date: date) -> DailyHealthMetric | None:
    return db.scalar(
        select(DailyHealthMetric)
        .where(
            DailyHealthMetric.athlete_id == athlete_id,
            DailyHealthMetric.metric_date == reference_date,
        )
        .order_by(DailyHealthMetric.updated_at.desc(), DailyHealthMetric.id.desc())
    )


def _get_first_session_for_date(
    db: Session,
    athlete_id: int,
    training_plan: TrainingPlan | None,
    reference_date: date,
) -> PlannedSession | None:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .options(selectinload(PlannedSession.training_day), selectinload(PlannedSession.activity_match))
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date == reference_date,
        )
        .order_by(PlannedSession.session_order.asc(), PlannedSession.id.asc())
        .limit(1)
    )
    if training_plan is not None:
        statement = statement.where(TrainingDay.training_plan_id == training_plan.id)
    return db.scalar(statement)


def _get_activities_for_date(db: Session, athlete_id: int, reference_date: date) -> list[GarminActivity]:
    start_dt = datetime.combine(reference_date - timedelta(days=1), datetime.min.time())
    end_dt = datetime.combine(reference_date + timedelta(days=2), datetime.min.time())
    statement = (
        select(GarminActivity)
        .options(
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session).selectinload(PlannedSession.training_day),
            selectinload(GarminActivity.session_analyses),
        )
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.start_time.is_not(None),
            GarminActivity.start_time >= start_dt,
            GarminActivity.start_time < end_dt,
        )
        .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
    )
    activities = list(db.scalars(statement).all())
    return [activity for activity in activities if activity_local_date(activity.start_time) == reference_date]


def _has_completed_analysis(activity: GarminActivity, planned_session_id: int) -> bool:
    for analysis in activity.session_analyses:
        if analysis.planned_session_id == planned_session_id and analysis.status.startswith("completed"):
            return True
    return False


def _build_step(key: str, status: str, message: str) -> dict[str, str]:
    return {"key": key, "status": status, "message": message}


def _elapsed_since(earlier: datetime, now: datetime) -> timedelta:
    current = earlier if earlier.tzinfo is not None else earlier.replace(tzinfo=timezone.utc)
    return now - current.astimezone(timezone.utc)


def _local_date(value: datetime) -> date:
    current = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return current.astimezone(APP_LOCAL_TIMEZONE).date()


def _controlled_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return "No hubo respuesta utilizable del servicio externo."
    return message[:300]
