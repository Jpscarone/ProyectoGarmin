from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.db.models.health_sync_state import HealthSyncState
from app.db.models.pending_training_item import PendingTrainingItem
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.services.analysis_v2.session_analysis_service import run_session_analysis
from app.services.health_ai_analysis_service import get_latest_health_ai_analysis_for_date
from app.services.health_readiness_service import build_health_readiness_summary, evaluate_health_readiness
from app.services.scheduled_sync_service import (
    SyncOperationResult,
    auto_link_new_activities_for_athlete,
    generate_health_ai_if_needed,
    generate_missing_activity_analyses,
    sync_activities_for_athlete,
    sync_health_for_athlete,
    update_weekly_analysis_if_needed,
)
from app.services.session_match_service import auto_match_activity, preview_activity_match
from app.utils.datetime_utils import now_utc, to_local_date, today_local


logger = logging.getLogger(__name__)

ITEM_ACTIVITY_UNLINKED = "activity_unlinked"
ITEM_SESSION_WITHOUT_ACTIVITY = "session_without_activity"
ITEM_ACTIVITY_WITHOUT_ANALYSIS = "activity_without_analysis"
ITEM_HEALTH_WITHOUT_READINESS = "health_without_readiness"
ITEM_READINESS_WITHOUT_AI = "readiness_without_ai_analysis"
ITEM_WEEK_WITHOUT_ANALYSIS = "week_without_analysis"
ITEM_GARMIN_SYNC_FAILED = "garmin_sync_failed"

STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"
STATUS_IGNORED = "ignored"
STATUS_FAILED = "failed"
ACTIVE_PENDING_STATUSES = {STATUS_PENDING, STATUS_FAILED}
MAX_PENDING_ATTEMPTS = 5
AUTO_LINK_PENDING_SCORE = 65.0


@dataclass(slots=True)
class PendingDetectionSummary:
    items: list[PendingTrainingItem]
    created_count: int


@dataclass(slots=True)
class PendingResolutionSummary:
    processed: int
    resolved: int
    still_pending: int
    failed: int
    detected: int = 0
    created: int = 0
    messages: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "resolved": self.resolved,
            "still_pending": self.still_pending,
            "failed": self.failed,
            "detected": self.detected,
            "created": self.created,
            "messages": list(self.messages or []),
        }


def detect_pending_items(
    db: Session,
    athlete_id: int,
    reference_date: date | None = None,
) -> PendingDetectionSummary:
    athlete = db.get(Athlete, athlete_id)
    if athlete is None:
        raise ValueError(f"No se encontro Athlete #{athlete_id}.")

    target_date = reference_date or today_local(athlete=athlete)
    created = 0
    touched_items: list[PendingTrainingItem] = []

    for activity in _list_unlinked_activities(db, athlete_id, target_date):
        preview = preview_activity_match(db, activity.id)
        candidate_count = len(preview.candidate_sessions)
        message = "Actividad encontrada pero no vinculada automaticamente."
        if candidate_count:
            message = f"{message} Hay {candidate_count} candidata(s) para revisar."
        item, was_created = create_or_update_pending_item(
            db,
            athlete_id=athlete_id,
            item_type=ITEM_ACTIVITY_UNLINKED,
            priority="high" if preview.status == "ambiguous" else "medium",
            reference_date=to_local_date(activity.start_time, athlete=athlete),
            garmin_activity_id=activity.id,
            title=activity.activity_name or "Actividad Garmin sin vincular",
            message=message,
            resolution_hint="Recalcular candidatos y vincular si aparece un match fuerte.",
        )
        touched_items.append(item)
        created += int(was_created)

    cutoff_date = target_date - timedelta(days=1)
    for session in _list_sessions_without_activity(db, athlete_id, cutoff_date):
        session_date = session.training_day.day_date if session.training_day else None
        item, was_created = create_or_update_pending_item(
            db,
            athlete_id=athlete_id,
            item_type=ITEM_SESSION_WITHOUT_ACTIVITY,
            priority="medium",
            reference_date=session_date,
            planned_session_id=session.id,
            title=f"Sesion sin actividad: {session.name}",
            message="Sesion planificada sin actividad vinculada. Puede que Garmin aun no haya subido la actividad.",
            resolution_hint="Buscar actividades Garmin de esa fecha y del dia siguiente local.",
        )
        touched_items.append(item)
        created += int(was_created)

    for activity in _list_activities_without_analysis(db, athlete_id, target_date):
        item, was_created = create_or_update_pending_item(
            db,
            athlete_id=athlete_id,
            item_type=ITEM_ACTIVITY_WITHOUT_ANALYSIS,
            priority="medium",
            reference_date=to_local_date(activity.start_time, athlete=athlete),
            garmin_activity_id=activity.id,
            planned_session_id=activity.activity_match.planned_session_id_fk if activity.activity_match else None,
            title=activity.activity_name or "Actividad vinculada sin analisis",
            message="La actividad tiene sesion vinculada pero todavia no tiene analisis.",
            resolution_hint="Generar SessionAnalysis para la actividad vinculada.",
        )
        touched_items.append(item)
        created += int(was_created)

    readiness_item = _detect_readiness_without_ai(db, athlete, target_date)
    if readiness_item is not None:
        item, was_created = create_or_update_pending_item(
            db,
            athlete_id=athlete_id,
            item_type=ITEM_READINESS_WITHOUT_AI,
            priority="medium",
            reference_date=target_date,
            title=f"Readiness sin IA {target_date.isoformat()}",
            message="Hay readiness calculado pero falta generar Health AI Analysis.",
            resolution_hint="Generar HealthAiAnalysis si los datos son suficientes.",
        )
        touched_items.append(item)
        created += int(was_created)

    week_item = _detect_week_without_analysis(db, athlete_id, target_date)
    if week_item:
        week_start = target_date - timedelta(days=target_date.weekday())
        item, was_created = create_or_update_pending_item(
            db,
            athlete_id=athlete_id,
            item_type=ITEM_WEEK_WITHOUT_ANALYSIS,
            priority="medium",
            reference_date=week_start,
            title=f"Semana sin analisis: {week_start.isoformat()}",
            message="La semana tiene carga o plan, pero todavia no existe WeeklyAnalysis.",
            resolution_hint="Generar o actualizar WeeklyAnalysis.",
        )
        touched_items.append(item)
        created += int(was_created)

    garmin_failure = _detect_garmin_sync_failure(db, athlete_id)
    if garmin_failure:
        item, was_created = create_or_update_pending_item(
            db,
            athlete_id=athlete_id,
            item_type=ITEM_GARMIN_SYNC_FAILED,
            priority="high",
            reference_date=target_date,
            title="Garmin sync fallo",
            message=garmin_failure,
            resolution_hint="Intentar una sincronizacion rapida cuando no haya cooldown ni rate limit.",
        )
        touched_items.append(item)
        created += int(was_created)

    return PendingDetectionSummary(items=touched_items, created_count=created)


def resolve_pending_item(
    db: Session,
    pending_item_id: int,
    *,
    force: bool = False,
) -> PendingTrainingItem:
    item = db.get(PendingTrainingItem, pending_item_id)
    if item is None:
        raise ValueError(f"No se encontro PendingTrainingItem #{pending_item_id}.")
    if item.status == STATUS_RESOLVED and not force:
        return item

    now = now_utc()
    item.last_attempt_at = now
    item.attempts_count = int(item.attempts_count or 0) + 1
    db.add(item)
    db.commit()
    db.refresh(item)

    try:
        _resolve_pending_item_impl(db, item, force=force)
    except Exception as exc:
        logger.exception("Pending item resolution failed item_id=%s", item.id)
        item.status = STATUS_FAILED if item.attempts_count >= MAX_PENDING_ATTEMPTS else STATUS_PENDING
        item.message = str(exc)[:400]
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    return item


def resolve_pending_items_for_athlete(
    db: Session,
    athlete_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    force: bool = False,
) -> PendingResolutionSummary:
    athlete = db.get(Athlete, athlete_id)
    target_reference_date = date_to or date_from or today_local(athlete=athlete)
    detection = detect_pending_items(db, athlete_id, reference_date=target_reference_date)
    statement = (
        select(PendingTrainingItem)
        .where(
            PendingTrainingItem.athlete_id == athlete_id,
            PendingTrainingItem.status.in_(ACTIVE_PENDING_STATUSES),
        )
        .order_by(PendingTrainingItem.created_at.asc(), PendingTrainingItem.id.asc())
    )
    if date_from is not None:
        statement = statement.where(
            (PendingTrainingItem.reference_date.is_(None)) | (PendingTrainingItem.reference_date >= date_from)
        )
    if date_to is not None:
        statement = statement.where(
            (PendingTrainingItem.reference_date.is_(None)) | (PendingTrainingItem.reference_date <= date_to)
        )

    items = list(db.scalars(statement).all())
    resolved = 0
    still_pending = 0
    failed = 0
    messages: list[str] = []

    for item in items:
        resolved_item = resolve_pending_item(db, item.id, force=force)
        if resolved_item.status == STATUS_RESOLVED:
            resolved += 1
            messages.append(f"Resuelto: {resolved_item.title}")
        elif resolved_item.status == STATUS_FAILED:
            failed += 1
            messages.append(f"Fallido: {resolved_item.title}")
        else:
            still_pending += 1
            messages.append(f"Sigue pendiente: {resolved_item.title}")

    return PendingResolutionSummary(
        processed=len(items),
        resolved=resolved,
        still_pending=still_pending,
        failed=failed,
        detected=len(detection.items),
        created=detection.created_count,
        messages=messages,
    )


def create_or_update_pending_item(
    db: Session,
    *,
    athlete_id: int,
    item_type: str,
    priority: str,
    title: str,
    message: str,
    resolution_hint: str | None = None,
    reference_date: date | None = None,
    garmin_activity_id: int | None = None,
    planned_session_id: int | None = None,
    analysis_report_id: int | None = None,
) -> tuple[PendingTrainingItem, bool]:
    existing = _find_matching_active_pending(
        db,
        athlete_id=athlete_id,
        item_type=item_type,
        reference_date=reference_date,
        garmin_activity_id=garmin_activity_id,
        planned_session_id=planned_session_id,
        analysis_report_id=analysis_report_id,
    )
    if existing is not None:
        existing.priority = priority
        existing.title = title
        existing.message = message
        existing.resolution_hint = resolution_hint
        existing.updated_at = now_utc()
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing, False

    item = PendingTrainingItem(
        athlete_id=athlete_id,
        item_type=item_type,
        priority=priority,
        reference_date=reference_date,
        garmin_activity_id=garmin_activity_id,
        planned_session_id=planned_session_id,
        analysis_report_id=analysis_report_id,
        title=title,
        message=message,
        resolution_hint=resolution_hint,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item, True


def _find_matching_active_pending(
    db: Session,
    *,
    athlete_id: int,
    item_type: str,
    reference_date: date | None,
    garmin_activity_id: int | None,
    planned_session_id: int | None,
    analysis_report_id: int | None,
) -> PendingTrainingItem | None:
    items = list(
        db.scalars(
            select(PendingTrainingItem)
            .where(
                PendingTrainingItem.athlete_id == athlete_id,
                PendingTrainingItem.item_type == item_type,
                PendingTrainingItem.status.in_(ACTIVE_PENDING_STATUSES),
            )
            .order_by(PendingTrainingItem.id.desc())
        ).all()
    )
    for item in items:
        if garmin_activity_id is not None and item.garmin_activity_id == garmin_activity_id:
            return item
        if planned_session_id is not None and item.planned_session_id == planned_session_id:
            return item
        if analysis_report_id is not None and item.analysis_report_id == analysis_report_id:
            return item
        if reference_date is not None and item.reference_date == reference_date:
            return item
    return None


def _resolve_pending_item_impl(db: Session, item: PendingTrainingItem, *, force: bool) -> None:
    if item.item_type == ITEM_ACTIVITY_UNLINKED:
        _resolve_activity_unlinked(db, item)
        return
    if item.item_type == ITEM_SESSION_WITHOUT_ACTIVITY:
        _resolve_session_without_activity(db, item)
        return
    if item.item_type == ITEM_ACTIVITY_WITHOUT_ANALYSIS:
        _resolve_activity_without_analysis(db, item)
        return
    if item.item_type == ITEM_HEALTH_WITHOUT_READINESS:
        _resolve_health_without_readiness(db, item)
        return
    if item.item_type == ITEM_READINESS_WITHOUT_AI:
        _resolve_readiness_without_ai(db, item, force=force)
        return
    if item.item_type == ITEM_WEEK_WITHOUT_ANALYSIS:
        _resolve_week_without_analysis(db, item, force=force)
        return
    if item.item_type == ITEM_GARMIN_SYNC_FAILED:
        _resolve_garmin_sync_failed(db, item, force=force)
        return
    raise ValueError(f"Tipo de pendiente no soportado: {item.item_type}")


def _resolve_activity_unlinked(db: Session, item: PendingTrainingItem) -> None:
    activity = db.get(GarminActivity, item.garmin_activity_id)
    if activity is None:
        _mark_pending_resolved(db, item, "La actividad ya no existe.")
        return
    if activity.activity_match is not None:
        _mark_pending_resolved(db, item, "La actividad ya quedo vinculada.")
        return

    preview = preview_activity_match(db, activity.id)
    if preview.status == "matched" and (preview.score or 0.0) >= AUTO_LINK_PENDING_SCORE:
        auto_match_activity(db, activity.id)
        activity = db.get(GarminActivity, activity.id)
        if activity is not None and activity.activity_match is not None:
            _mark_pending_resolved(db, item, "La actividad se vinculo automaticamente.")
            return

    candidate_count = len(preview.candidate_sessions)
    item.status = STATUS_FAILED if item.attempts_count >= MAX_PENDING_ATTEMPTS else STATUS_PENDING
    item.message = (
        f"Actividad aun sin vincular. Estado match: {preview.status}. "
        f"Candidatas actuales: {candidate_count}."
    )
    db.add(item)
    db.commit()


def _resolve_session_without_activity(db: Session, item: PendingTrainingItem) -> None:
    session = db.get(PlannedSession, item.planned_session_id)
    if session is None or session.training_day is None:
        _mark_pending_resolved(db, item, "La sesion ya no existe.")
        return
    if session.activity_match is not None:
        _mark_pending_resolved(db, item, "La sesion ya tiene actividad vinculada.")
        return

    reference_date = session.training_day.day_date
    auto_link_new_activities_for_athlete(
        db,
        athlete_id=session.athlete_id,
        date_from=reference_date,
        date_to=reference_date + timedelta(days=1),
    )
    session = db.get(PlannedSession, item.planned_session_id)
    if session is not None and session.activity_match is not None:
        _mark_pending_resolved(db, item, "Se encontro una actividad para la sesion.")
        return

    item.status = STATUS_FAILED if item.attempts_count >= MAX_PENDING_ATTEMPTS else STATUS_PENDING
    item.message = "La sesion sigue sin actividad vinculada."
    db.add(item)
    db.commit()


def _resolve_activity_without_analysis(db: Session, item: PendingTrainingItem) -> None:
    activity = db.get(GarminActivity, item.garmin_activity_id)
    if activity is None:
        _mark_pending_resolved(db, item, "La actividad ya no existe.")
        return
    if activity.activity_match is None or activity.activity_match.planned_session_id_fk is None:
        item.status = STATUS_PENDING
        item.message = "La actividad sigue sin sesion vinculada."
        db.add(item)
        db.commit()
        return
    if _activity_has_completed_analysis(activity):
        _mark_pending_resolved(db, item, "La actividad ya tiene analisis.")
        return

    run_session_analysis(
        db,
        planned_session_id=activity.activity_match.planned_session_id_fk,
        activity_id=activity.id,
        trigger_source="resolve_pending",
    )
    activity = db.get(GarminActivity, activity.id)
    if activity is not None and _activity_has_completed_analysis(activity):
        _mark_pending_resolved(db, item, "Se genero el analisis faltante.")
        return

    item.status = STATUS_PENDING
    item.message = "No se pudo generar el analisis automaticamente."
    db.add(item)
    db.commit()


def _resolve_health_without_readiness(db: Session, item: PendingTrainingItem) -> None:
    athlete = db.get(Athlete, item.athlete_id)
    reference_date = item.reference_date or today_local(athlete=athlete)
    summary = build_health_readiness_summary(db, item.athlete_id, reference_date)
    evaluation = evaluate_health_readiness(summary)
    if evaluation.readiness_score is not None:
        _mark_pending_resolved(db, item, "Readiness recalculado correctamente.")
        return
    item.status = STATUS_PENDING
    item.message = "Todavia no hay datos suficientes para readiness."
    db.add(item)
    db.commit()


def _resolve_readiness_without_ai(db: Session, item: PendingTrainingItem, *, force: bool) -> None:
    athlete = db.get(Athlete, item.athlete_id)
    reference_date = item.reference_date or today_local(athlete=athlete)
    result = generate_health_ai_if_needed(
        db,
        athlete_id=item.athlete_id,
        reference_date=reference_date,
        force=force,
        source="pending_resolver",
    )
    if result.status in {"success", "skipped"}:
        analysis = get_latest_health_ai_analysis_for_date(db, item.athlete_id, reference_date)
        if analysis is not None:
            _mark_pending_resolved(db, item, "Health AI Analysis disponible.")
            return
    item.status = STATUS_PENDING
    item.message = result.message
    db.add(item)
    db.commit()


def _resolve_week_without_analysis(db: Session, item: PendingTrainingItem, *, force: bool) -> None:
    athlete = db.get(Athlete, item.athlete_id)
    reference_date = item.reference_date or today_local(athlete=athlete)
    result = update_weekly_analysis_if_needed(
        db,
        athlete_id=item.athlete_id,
        reference_date=reference_date,
        force=force,
    )
    week_start = reference_date - timedelta(days=reference_date.weekday())
    weekly = db.scalar(
        select(WeeklyAnalysis)
        .where(
            WeeklyAnalysis.athlete_id == item.athlete_id,
            WeeklyAnalysis.week_start_date == week_start,
        )
        .order_by(WeeklyAnalysis.id.desc())
    )
    if weekly is not None:
        _mark_pending_resolved(db, item, "WeeklyAnalysis disponible.")
        return
    item.status = STATUS_PENDING
    item.message = result.message
    db.add(item)
    db.commit()


def _resolve_garmin_sync_failed(db: Session, item: PendingTrainingItem, *, force: bool) -> None:
    athlete = db.get(Athlete, item.athlete_id)
    reference_date = item.reference_date or today_local(athlete=athlete)
    health_result = sync_health_for_athlete(
        db,
        athlete_id=item.athlete_id,
        start_date=reference_date - timedelta(days=1),
        end_date=reference_date,
        force=force,
    )
    activities_result = sync_activities_for_athlete(
        db,
        athlete_id=item.athlete_id,
        start_date=reference_date - timedelta(days=1),
        end_date=reference_date,
        force=force,
    )
    if health_result.status != "failed" or activities_result.status != "failed":
        _mark_pending_resolved(db, item, "La sincronizacion rapida pudo ejecutarse nuevamente.")
        return
    item.status = STATUS_FAILED if item.attempts_count >= MAX_PENDING_ATTEMPTS else STATUS_PENDING
    item.message = f"{health_result.message} | {activities_result.message}"
    db.add(item)
    db.commit()


def _mark_pending_resolved(db: Session, item: PendingTrainingItem, message: str) -> None:
    item.status = STATUS_RESOLVED
    item.message = message
    item.resolved_at = now_utc()
    db.add(item)
    db.commit()


def _list_unlinked_activities(db: Session, athlete_id: int, reference_date: date) -> list[GarminActivity]:
    statement = (
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.start_time.is_not(None),
        )
        .options(selectinload(GarminActivity.activity_match))
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
    )
    activities = list(db.scalars(statement).all())
    return [
        activity
        for activity in activities
        if activity.activity_match is None and to_local_date(activity.start_time) is not None and to_local_date(activity.start_time) <= reference_date
    ]


def _list_sessions_without_activity(db: Session, athlete_id: int, cutoff_date: date) -> list[PlannedSession]:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date <= cutoff_date,
        )
        .options(selectinload(PlannedSession.training_day), selectinload(PlannedSession.activity_match))
        .order_by(TrainingDay.day_date.desc(), PlannedSession.id.desc())
    )
    return [session for session in db.scalars(statement).all() if session.activity_match is None]


def _list_activities_without_analysis(db: Session, athlete_id: int, reference_date: date) -> list[GarminActivity]:
    statement = (
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.start_time.is_not(None),
        )
        .options(
            selectinload(GarminActivity.activity_match).selectinload(ActivitySessionMatch.planned_session),
            selectinload(GarminActivity.session_analyses),
        )
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
    )
    activities = list(db.scalars(statement).all())
    result: list[GarminActivity] = []
    for activity in activities:
        activity_date = to_local_date(activity.start_time)
        if activity_date is None or activity_date > reference_date:
            continue
        if activity.activity_match is None:
            continue
        if not _activity_has_completed_analysis(activity):
            result.append(activity)
    return result


def _activity_has_completed_analysis(activity: GarminActivity) -> bool:
    return any(analysis.status.startswith("completed") for analysis in activity.session_analyses)


def _detect_readiness_without_ai(db: Session, athlete: Athlete, reference_date: date) -> bool:
    metric = db.scalar(
        select(DailyHealthMetric)
        .where(
            DailyHealthMetric.athlete_id == athlete.id,
            DailyHealthMetric.metric_date == reference_date,
        )
        .order_by(DailyHealthMetric.id.desc())
    )
    if metric is None:
        return False
    summary = build_health_readiness_summary(db, athlete.id, reference_date)
    evaluation = evaluate_health_readiness(summary)
    if evaluation.readiness_score is None:
        return False
    existing_ai = db.scalar(
        select(HealthAiAnalysis)
        .where(
            HealthAiAnalysis.athlete_id == athlete.id,
            HealthAiAnalysis.reference_date == reference_date,
        )
        .order_by(HealthAiAnalysis.id.desc())
    )
    return existing_ai is None


def _detect_week_without_analysis(db: Session, athlete_id: int, reference_date: date) -> bool:
    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)
    weekly = db.scalar(
        select(WeeklyAnalysis)
        .where(
            WeeklyAnalysis.athlete_id == athlete_id,
            WeeklyAnalysis.week_start_date == week_start,
        )
        .order_by(WeeklyAnalysis.id.desc())
    )
    if weekly is not None:
        return False

    has_health_or_activity = db.scalar(
        select(DailyHealthMetric.id)
        .where(
            DailyHealthMetric.athlete_id == athlete_id,
            DailyHealthMetric.metric_date >= week_start,
            DailyHealthMetric.metric_date <= week_end,
        )
        .limit(1)
    )
    has_plan = db.scalar(
        select(PlannedSession.id)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date >= week_start,
            TrainingDay.day_date <= week_end,
        )
        .limit(1)
    )
    return bool(has_health_or_activity or has_plan)


def _detect_garmin_sync_failure(db: Session, athlete_id: int) -> str | None:
    health_state = db.scalar(
        select(HealthSyncState)
        .where(
            HealthSyncState.athlete_id == athlete_id,
            HealthSyncState.status == "failed",
        )
        .order_by(HealthSyncState.updated_at.desc(), HealthSyncState.id.desc())
    )
    if health_state is not None:
        return health_state.error_message or "La sincronizacion de salud Garmin fallo."
    return None
