from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_account import GarminAccount
from app.db.models.garmin_activity import GarminActivity
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.db.models.scheduled_sync_job_log import ScheduledSyncJobLog
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.services.analysis_v2.session_analysis_service import ANALYSIS_VERSION as SESSION_ANALYSIS_VERSION
from app.services.analysis_v2.session_analysis_service import run_session_analysis
from app.services.analysis_v2.weekly_analysis_service import ANALYSIS_VERSION as WEEKLY_ANALYSIS_VERSION
from app.services.analysis_v2.weekly_analysis_service import run_weekly_analysis
from app.services.garmin_credential_service import (
    GarminCredentialConfigurationError,
    GarminCredentialDecryptError,
    default_token_dir_for_athlete,
    get_or_create_garmin_account,
    resolve_garmin_credentials,
)
from app.services.security import GarminCredentialBundle
from app.services.garmin.activity_sync import sync_activities_by_date
from app.services.garmin.auth import get_garmin_auth_context
from app.services.garmin.client import GarminClient
from app.services.garmin.health_sync import _build_health_values, _get_sync_athlete, _merge_metric_values
from app.services.health_ai_analysis_service import (
    get_latest_health_ai_analysis_for_date,
    get_or_create_health_ai_analysis,
)
from app.services.health_readiness_service import (
    build_health_readiness_summary,
    evaluate_health_readiness,
)
from app.services.openai_client import OpenAIIntegrationError
from app.services.session_match_service import auto_match_unlinked_activities
from app.utils.datetime_utils import local_date_range_utc_bounds, now_utc, today_local, to_local_date, to_local_datetime


logger = logging.getLogger(__name__)

JOB_TYPE_MORNING_HEALTH = "morning_health"
JOB_TYPE_EVENING_FULL = "evening_full"
JOB_TYPE_RESOLVE_PENDING = "resolve_pending"
JOB_LOCK_MINUTES = 120
JOB_STALE_HOURS = 2


@dataclass(slots=True)
class SyncOperationResult:
    status: str
    message: str
    activities_created: int = 0
    activities_updated: int = 0
    activities_linked: int = 0
    activity_analyses_created: int = 0
    health_days_synced: int = 0
    health_ai_analyses_created: int = 0
    weekly_analyses_created: int = 0
    pending_items_created: int = 0
    pending_items_resolved: int = 0
    created_activity_ids: list[int] = field(default_factory=list)
    error_detail: str | None = None


@dataclass(slots=True)
class ScheduledJobRunSummary:
    job_type: str
    reference_date: date
    started_at: datetime
    finished_at: datetime | None
    status: str
    message: str
    athletes_considered: int
    athletes_processed: int
    athletes_succeeded: int
    athletes_failed: int
    athletes_skipped: int = 0
    activities_created: int = 0
    activities_updated: int = 0
    activities_linked: int = 0
    activity_analyses_created: int = 0
    health_days_synced: int = 0
    health_ai_analyses_created: int = 0
    weekly_analyses_created: int = 0
    pending_items_created: int = 0
    pending_items_resolved: int = 0
    log_id: int | None = None
    error_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_id": self.log_id,
            "job_type": self.job_type,
            "reference_date": self.reference_date.isoformat(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status,
            "message": self.message,
            "athletes_considered": self.athletes_considered,
            "athletes_processed": self.athletes_processed,
            "athletes_succeeded": self.athletes_succeeded,
            "athletes_failed": self.athletes_failed,
            "athletes_skipped": self.athletes_skipped,
            "activities_created": self.activities_created,
            "activities_updated": self.activities_updated,
            "activities_linked": self.activities_linked,
            "activity_analyses_created": self.activity_analyses_created,
            "health_days_synced": self.health_days_synced,
            "health_ai_analyses_created": self.health_ai_analyses_created,
            "weekly_analyses_created": self.weekly_analyses_created,
            "pending_items_created": self.pending_items_created,
            "pending_items_resolved": self.pending_items_resolved,
            "error_detail": self.error_detail,
        }


def utc_now() -> datetime:
    return now_utc()


def local_today() -> date:
    return today_local()


def sync_health_for_athlete(
    db: Session,
    *,
    athlete_id: int,
    start_date: date,
    end_date: date,
    force: bool = False,
    settings: Settings | None = None,
) -> SyncOperationResult:
    del force
    sync_settings = settings or get_settings()
    prep = _prepare_garmin_sync(db, sync_settings, athlete_id)
    if prep.skip_result is not None:
        return prep.skip_result
    if prep.failed_result is not None:
        return prep.failed_result
    athlete = prep.athlete
    account = prep.account
    credentials = prep.credentials
    if athlete is None or account is None or credentials is None:
        return SyncOperationResult(status="failed", message="No se pudo preparar el sync de salud.", error_detail="garmin_sync_setup_failed")
    reviewed_dates = _date_range(start_date, end_date)
    existing_by_date = {
        metric.metric_date: metric
        for metric in db.scalars(select(DailyHealthMetric).where(DailyHealthMetric.athlete_id == athlete.id)).all()
    }
    auth_context = get_garmin_auth_context(sync_settings, credentials)
    client = GarminClient(auth_context.client)

    created = 0
    updated = 0
    days_synced = 0
    errors: list[str] = []

    for metric_date in reviewed_dates:
        try:
            payloads = client.get_health_payloads(metric_date)
            values = _build_health_values(athlete.id, metric_date, payloads)
            has_any_metric = any(
                value is not None
                for key, value in values.items()
                if key not in {"athlete_id", "metric_date", "raw_health_json"}
            )
            if not has_any_metric and values["raw_health_json"] is None:
                continue

            existing = existing_by_date.get(metric_date)
            if existing is None:
                db.add(DailyHealthMetric(**values))
                created += 1
                days_synced += 1
            else:
                if _merge_metric_values(existing, values):
                    updated += 1
                    days_synced += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Scheduled health sync failed athlete_id=%s metric_date=%s", athlete.id, metric_date.isoformat())
            errors.append(f"{metric_date.isoformat()}: {exc}")

    account = _get_active_garmin_account(db, athlete.id)
    if account is not None:
        account.last_health_sync_at = utc_now()
        db.add(account)
        db.commit()

    status = "success" if not errors else ("partial_success" if days_synced > 0 or created > 0 or updated > 0 else "failed")
    message = (
        f"Salud {start_date.isoformat()}..{end_date.isoformat()}: "
        f"{days_synced} dias sincronizados, {created} creados, {updated} actualizados."
    )
    if errors:
        message = f"{message} Errores: {len(errors)}."
    return SyncOperationResult(
        status=status,
        message=message,
        health_days_synced=days_synced,
        error_detail="\n".join(errors) if errors else None,
    )


def sync_activities_for_athlete(
    db: Session,
    *,
    athlete_id: int,
    start_date: date,
    end_date: date,
    force: bool = False,
    settings: Settings | None = None,
) -> SyncOperationResult:
    del force
    sync_settings = settings or get_settings()
    prep = _prepare_garmin_sync(db, sync_settings, athlete_id)
    if prep.skip_result is not None:
        return prep.skip_result
    if prep.failed_result is not None:
        return prep.failed_result
    before = {
        item.garmin_activity_id: item.id
        for item in db.scalars(select(GarminActivity).where(GarminActivity.athlete_id == athlete_id)).all()
    }
    result = sync_activities_by_date(
        db,
        sync_settings,
        start_date=start_date,
        end_date=end_date,
        athlete_id=athlete_id,
    )
    after = {
        item.garmin_activity_id: item.id
        for item in db.scalars(select(GarminActivity).where(GarminActivity.athlete_id == athlete_id)).all()
    }
    created_ids = [activity_id for garmin_id, activity_id in after.items() if garmin_id not in before]
    status = "success" if not result.errors else ("partial_success" if (result.inserted or result.existing) else "failed")
    message = (
        f"Actividades {start_date.isoformat()}..{end_date.isoformat()}: "
        f"{result.inserted} nuevas, {result.existing} actualizadas."
    )
    if result.errors:
        message = f"{message} Errores: {len(result.errors)}."
    return SyncOperationResult(
        status=status,
        message=message,
        activities_created=result.inserted,
        activities_updated=result.existing,
        created_activity_ids=created_ids,
        error_detail="\n".join(result.errors) if result.errors else None,
    )


def auto_link_new_activities_for_athlete(
    db: Session,
    *,
    athlete_id: int,
    date_from: date,
    date_to: date,
) -> SyncOperationResult:
    decision = auto_match_unlinked_activities(
        db,
        athlete_id=athlete_id,
        date_from=date_from,
        date_to=date_to,
        only_unmatched=True,
    )
    linked = sum(1 for item in decision.decisions if item.status == "matched")
    message = f"Matching automatico: {decision.processed} revisadas, {linked} vinculadas."
    return SyncOperationResult(
        status="success",
        message=message,
        activities_linked=linked,
    )


def generate_missing_activity_analyses(
    db: Session,
    *,
    athlete_id: int,
    date_from: date,
    date_to: date,
) -> SyncOperationResult:
    activities = _list_activities_for_window(db, athlete_id=athlete_id, date_from=date_from, date_to=date_to)
    created = 0
    errors: list[str] = []

    for activity in activities:
        if activity.activity_match is None or activity.activity_match.planned_session_id_fk is None:
            continue
        if not _activity_needs_analysis(activity):
            continue
        try:
            analysis = run_session_analysis(
                db,
                planned_session_id=activity.activity_match.planned_session_id_fk,
                activity_id=activity.id,
                trigger_source="scheduled_sync",
            )
            if analysis.status.startswith("completed"):
                created += 1
        except Exception as exc:
            logger.exception(
                "Scheduled session analysis failed athlete_id=%s activity_id=%s",
                athlete_id,
                activity.id,
            )
            errors.append(f"activity_id={activity.id}: {exc}")

    status = "success" if not errors else ("partial_success" if created > 0 else "failed")
    message = f"Analisis de sesion: {created} creados."
    if errors:
        message = f"{message} Errores: {len(errors)}."
    return SyncOperationResult(
        status=status,
        message=message,
        activity_analyses_created=created,
        error_detail="\n".join(errors) if errors else None,
    )


def generate_health_ai_if_needed(
    db: Session,
    *,
    athlete_id: int,
    reference_date: date,
    force: bool = False,
    source: str = "scheduled",
) -> SyncOperationResult:
    summary = build_health_readiness_summary(db, athlete_id, reference_date)
    evaluation = evaluate_health_readiness(summary)
    if evaluation.readiness_score is None:
        return SyncOperationResult(
            status="skipped",
            message=f"Health AI omitido para {reference_date.isoformat()} por datos insuficientes.",
        )

    existing = get_latest_health_ai_analysis_for_date(db, athlete_id, reference_date)
    analysis, result_kind = get_or_create_health_ai_analysis(
        db,
        athlete_id=athlete_id,
        reference_date=reference_date,
        force=force,
        source=source,
    )
    if analysis is None:
        return SyncOperationResult(
            status="skipped",
            message=f"Health AI omitido para {reference_date.isoformat()} por datos insuficientes.",
        )
    if result_kind == "existing":
        return SyncOperationResult(
            status="skipped",
            message=f"Health AI ya existe para {reference_date.isoformat()}.",
        )
    if result_kind == "updated":
        return SyncOperationResult(
            status="success",
            message=f"Health AI actualizado para {reference_date.isoformat()}.",
        )
    return SyncOperationResult(
        status="success",
        message=f"Health AI generado para {reference_date.isoformat()}.",
        health_ai_analyses_created=1,
    )


def update_weekly_analysis_if_needed(
    db: Session,
    *,
    athlete_id: int,
    reference_date: date,
    force: bool = False,
) -> SyncOperationResult:
    week_start = reference_date - timedelta(days=reference_date.weekday())
    existing = db.scalar(
        select(WeeklyAnalysis)
        .where(
            WeeklyAnalysis.athlete_id == athlete_id,
            WeeklyAnalysis.week_start_date == week_start,
            WeeklyAnalysis.analysis_version == WEEKLY_ANALYSIS_VERSION,
        )
        .order_by(WeeklyAnalysis.id.desc())
    )
    if existing is not None and not force and existing.analyzed_at is not None:
        analyzed_local_date = _to_local_datetime(existing.analyzed_at).date()
        if analyzed_local_date >= reference_date:
            return SyncOperationResult(
                status="skipped",
                message=f"Weekly analysis ya estaba actualizado para la semana de {week_start.isoformat()}.",
            )

    run_weekly_analysis(
        db,
        athlete_id=athlete_id,
        reference_date=reference_date,
        trigger_source="scheduled_sync",
    )
    return SyncOperationResult(
        status="success",
        message=f"Weekly analysis actualizado para la semana de {week_start.isoformat()}.",
        weekly_analyses_created=0 if existing is not None else 1,
    )


def run_morning_health_job(
    db: Session,
    *,
    reference_date: date | None = None,
    athlete_id: int | None = None,
    force: bool = False,
    settings: Settings | None = None,
) -> ScheduledJobRunSummary:
    sync_settings = settings or get_settings()
    run_date = reference_date or local_today()
    start_time = utc_now()
    blocking = _find_blocking_running_job(db, JOB_TYPE_MORNING_HEALTH, now=start_time)
    if blocking is not None:
        skip_log = _create_skipped_log(db, JOB_TYPE_MORNING_HEALTH, blocking, now=start_time)
        return ScheduledJobRunSummary(
            job_type=JOB_TYPE_MORNING_HEALTH,
            reference_date=run_date,
            started_at=skip_log.started_at,
            finished_at=skip_log.finished_at,
            status=skip_log.status,
            message=skip_log.message or "Job omitido por lock.",
            athletes_considered=0,
            athletes_processed=0,
            athletes_succeeded=0,
            athletes_failed=0,
            athletes_skipped=0,
            log_id=skip_log.id,
            error_detail=skip_log.error_detail,
        )

    athletes = _get_target_athletes(db, sync_settings, athlete_id=athlete_id)
    stale_note = _build_stale_note(db, JOB_TYPE_MORNING_HEALTH, start_time)
    job_log = _create_running_log(db, JOB_TYPE_MORNING_HEALTH, start_time, message=stale_note or "Job en ejecucion.")
    summary = ScheduledJobRunSummary(
        job_type=JOB_TYPE_MORNING_HEALTH,
        reference_date=run_date,
        started_at=start_time,
        finished_at=None,
        status="running",
        message=stale_note or "Job en ejecucion.",
        athletes_considered=len(athletes),
        athletes_processed=0,
        athletes_succeeded=0,
        athletes_failed=0,
        athletes_skipped=0,
        log_id=job_log.id,
    )
    athlete_errors: list[str] = []

    try:
        if not athletes:
            summary.status = "skipped"
            summary.message = "No hay atletas activos con Garmin configurado para el job morning_health."
            return _finalize_job_log(db, job_log, summary)

        for athlete in athletes:
            summary.athletes_processed += 1
            try:
                health_result = sync_health_for_athlete(
                    db,
                    athlete_id=athlete.id,
                    start_date=run_date - timedelta(days=1),
                    end_date=run_date,
                    force=force,
                    settings=sync_settings,
                )
                if _is_missing_garmin_skip(health_result):
                    summary.athletes_skipped += 1
                    continue
                ai_result = generate_health_ai_if_needed(
                    db,
                    athlete_id=athlete.id,
                    reference_date=run_date,
                    force=force,
                )
                _recalculate_readiness(db, athlete.id, run_date)
                summary.health_days_synced += health_result.health_days_synced
                summary.health_ai_analyses_created += ai_result.health_ai_analyses_created
                if health_result.status in {"failed"} or ai_result.status in {"failed"}:
                    summary.athletes_failed += 1
                    athlete_errors.append(_athlete_error_message(athlete, [health_result, ai_result]))
                else:
                    summary.athletes_succeeded += 1
            except OpenAIIntegrationError as exc:
                summary.athletes_failed += 1
                athlete_errors.append(f"{athlete.name}: fallo Health AI ({exc})")
            except Exception as exc:
                logger.exception("Morning scheduled sync failed athlete_id=%s", athlete.id)
                summary.athletes_failed += 1
                athlete_errors.append(f"{athlete.name}: {exc}")

        summary.finished_at = utc_now()
        summary.status = _resolve_summary_status(summary, athlete_errors)
        summary.message = _build_summary_message(summary)
        summary.error_detail = "\n".join(athlete_errors) if athlete_errors else None
        return _finalize_job_log(db, job_log, summary)
    except Exception:
        logger.exception("Morning scheduled sync job failed")
        summary.finished_at = utc_now()
        summary.status = "failed"
        summary.message = "El job morning_health fallo de forma inesperada."
        summary.error_detail = "\n".join(athlete_errors) if athlete_errors else None
        return _finalize_job_log(db, job_log, summary)


def run_evening_full_job(
    db: Session,
    *,
    reference_date: date | None = None,
    athlete_id: int | None = None,
    force: bool = False,
    settings: Settings | None = None,
) -> ScheduledJobRunSummary:
    sync_settings = settings or get_settings()
    run_date = reference_date or local_today()
    start_time = utc_now()
    blocking = _find_blocking_running_job(db, JOB_TYPE_EVENING_FULL, now=start_time)
    if blocking is not None:
        skip_log = _create_skipped_log(db, JOB_TYPE_EVENING_FULL, blocking, now=start_time)
        return ScheduledJobRunSummary(
            job_type=JOB_TYPE_EVENING_FULL,
            reference_date=run_date,
            started_at=skip_log.started_at,
            finished_at=skip_log.finished_at,
            status=skip_log.status,
            message=skip_log.message or "Job omitido por lock.",
            athletes_considered=0,
            athletes_processed=0,
            athletes_succeeded=0,
            athletes_failed=0,
            athletes_skipped=0,
            log_id=skip_log.id,
            error_detail=skip_log.error_detail,
        )

    athletes = _get_target_athletes(db, sync_settings, athlete_id=athlete_id)
    stale_note = _build_stale_note(db, JOB_TYPE_EVENING_FULL, start_time)
    job_log = _create_running_log(db, JOB_TYPE_EVENING_FULL, start_time, message=stale_note or "Job en ejecucion.")
    summary = ScheduledJobRunSummary(
        job_type=JOB_TYPE_EVENING_FULL,
        reference_date=run_date,
        started_at=start_time,
        finished_at=None,
        status="running",
        message=stale_note or "Job en ejecucion.",
        athletes_considered=len(athletes),
        athletes_processed=0,
        athletes_succeeded=0,
        athletes_failed=0,
        athletes_skipped=0,
        log_id=job_log.id,
    )
    athlete_errors: list[str] = []

    try:
        if not athletes:
            summary.status = "skipped"
            summary.message = "No hay atletas activos con Garmin configurado para el job evening_full."
            return _finalize_job_log(db, job_log, summary)

        for athlete in athletes:
            summary.athletes_processed += 1
            try:
                activity_start = _infer_activity_sync_start_date(db, athlete.id, run_date, force=force)
                activities_result = sync_activities_for_athlete(
                    db,
                    athlete_id=athlete.id,
                    start_date=activity_start,
                    end_date=run_date,
                    force=force,
                    settings=sync_settings,
                )
                if _is_missing_garmin_skip(activities_result):
                    summary.athletes_skipped += 1
                    continue
                health_result = sync_health_for_athlete(
                    db,
                    athlete_id=athlete.id,
                    start_date=run_date - timedelta(days=1),
                    end_date=run_date,
                    force=force,
                    settings=sync_settings,
                )
                if _is_missing_garmin_skip(health_result):
                    summary.athletes_skipped += 1
                    continue
                link_result = auto_link_new_activities_for_athlete(
                    db,
                    athlete_id=athlete.id,
                    date_from=activity_start,
                    date_to=run_date,
                )
                analysis_result = generate_missing_activity_analyses(
                    db,
                    athlete_id=athlete.id,
                    date_from=activity_start,
                    date_to=run_date,
                )
                weekly_result = update_weekly_analysis_if_needed(
                    db,
                    athlete_id=athlete.id,
                    reference_date=run_date,
                    force=force,
                )
                from app.services.pending_training_service import detect_pending_items

                pending_detection = detect_pending_items(
                    db,
                    athlete_id=athlete.id,
                    reference_date=run_date,
                )
                _recalculate_readiness(db, athlete.id, run_date)

                summary.activities_created += activities_result.activities_created
                summary.activities_updated += activities_result.activities_updated
                summary.activities_linked += link_result.activities_linked
                summary.activity_analyses_created += analysis_result.activity_analyses_created
                summary.health_days_synced += health_result.health_days_synced
                summary.weekly_analyses_created += weekly_result.weekly_analyses_created
                summary.pending_items_created += pending_detection.created_count

                if any(
                    item.status == "failed"
                    for item in (activities_result, health_result, link_result, analysis_result, weekly_result)
                ):
                    summary.athletes_failed += 1
                    athlete_errors.append(
                        _athlete_error_message(
                            athlete,
                            [activities_result, health_result, link_result, analysis_result, weekly_result],
                        )
                    )
                else:
                    summary.athletes_succeeded += 1
            except Exception as exc:
                logger.exception("Evening scheduled sync failed athlete_id=%s", athlete.id)
                summary.athletes_failed += 1
                athlete_errors.append(f"{athlete.name}: {exc}")

        summary.finished_at = utc_now()
        summary.status = _resolve_summary_status(summary, athlete_errors)
        summary.message = _build_summary_message(summary)
        summary.error_detail = "\n".join(athlete_errors) if athlete_errors else None
        return _finalize_job_log(db, job_log, summary)
    except Exception:
        logger.exception("Evening scheduled sync job failed")
        summary.finished_at = utc_now()
        summary.status = "failed"
        summary.message = "El job evening_full fallo de forma inesperada."
        summary.error_detail = "\n".join(athlete_errors) if athlete_errors else None
        return _finalize_job_log(db, job_log, summary)


def run_resolve_pending_job(
    db: Session,
    *,
    reference_date: date | None = None,
    athlete_id: int | None = None,
    force: bool = False,
    settings: Settings | None = None,
) -> ScheduledJobRunSummary:
    del settings
    from app.services.pending_training_service import resolve_pending_items_for_athlete

    run_date = reference_date or local_today()
    start_time = utc_now()
    blocking = _find_blocking_running_job(db, JOB_TYPE_RESOLVE_PENDING, now=start_time)
    if blocking is not None:
        skip_log = _create_skipped_log(db, JOB_TYPE_RESOLVE_PENDING, blocking, now=start_time)
        return ScheduledJobRunSummary(
            job_type=JOB_TYPE_RESOLVE_PENDING,
            reference_date=run_date,
            started_at=skip_log.started_at,
            finished_at=skip_log.finished_at,
            status=skip_log.status,
            message=skip_log.message or "Job omitido por lock.",
            athletes_considered=0,
            athletes_processed=0,
            athletes_succeeded=0,
            athletes_failed=0,
            athletes_skipped=0,
            log_id=skip_log.id,
            error_detail=skip_log.error_detail,
        )

    athletes = _get_target_athletes(db, get_settings(), athlete_id=athlete_id)
    stale_note = _build_stale_note(db, JOB_TYPE_RESOLVE_PENDING, start_time)
    job_log = _create_running_log(db, JOB_TYPE_RESOLVE_PENDING, start_time, message=stale_note or "Job en ejecucion.")
    summary = ScheduledJobRunSummary(
        job_type=JOB_TYPE_RESOLVE_PENDING,
        reference_date=run_date,
        started_at=start_time,
        finished_at=None,
        status="running",
        message=stale_note or "Job en ejecucion.",
        athletes_considered=len(athletes),
        athletes_processed=0,
        athletes_succeeded=0,
        athletes_failed=0,
        athletes_skipped=0,
        log_id=job_log.id,
    )
    athlete_errors: list[str] = []

    try:
        if not athletes:
            summary.status = "skipped"
            summary.message = "No hay atletas activos con Garmin configurado para resolver pendientes."
            return _finalize_job_log(db, job_log, summary)

        for athlete in athletes:
            summary.athletes_processed += 1
            try:
                result = resolve_pending_items_for_athlete(
                    db,
                    athlete.id,
                    date_to=run_date,
                    force=force,
                )
                summary.pending_items_created += result.created
                summary.pending_items_resolved += result.resolved
                if result.failed > 0:
                    summary.athletes_failed += 1
                    athlete_errors.append(f"{athlete.name}: {result.failed} pendientes fallaron.")
                else:
                    summary.athletes_succeeded += 1
            except Exception as exc:
                logger.exception("Resolve pending job failed athlete_id=%s", athlete.id)
                summary.athletes_failed += 1
                athlete_errors.append(f"{athlete.name}: {exc}")

        summary.finished_at = utc_now()
        summary.status = _resolve_summary_status(summary, athlete_errors)
        summary.message = _build_summary_message(summary)
        summary.error_detail = "\n".join(athlete_errors) if athlete_errors else None
        return _finalize_job_log(db, job_log, summary)
    except Exception:
        logger.exception("Resolve pending scheduled job failed")
        summary.finished_at = utc_now()
        summary.status = "failed"
        summary.message = "El job resolve_pending fallo de forma inesperada."
        summary.error_detail = "\n".join(athlete_errors) if athlete_errors else None
        return _finalize_job_log(db, job_log, summary)


def get_latest_scheduled_sync_overview(db: Session) -> dict[str, dict[str, Any] | None]:
    return {
        JOB_TYPE_MORNING_HEALTH: _serialize_job_log(_latest_job_log(db, JOB_TYPE_MORNING_HEALTH)),
        JOB_TYPE_EVENING_FULL: _serialize_job_log(_latest_job_log(db, JOB_TYPE_EVENING_FULL)),
        JOB_TYPE_RESOLVE_PENDING: _serialize_job_log(_latest_job_log(db, JOB_TYPE_RESOLVE_PENDING)),
    }


def get_scheduled_sync_history(db: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    logs = list(
        db.scalars(
            select(ScheduledSyncJobLog)
            .where(ScheduledSyncJobLog.athlete_id.is_(None))
            .order_by(ScheduledSyncJobLog.started_at.desc(), ScheduledSyncJobLog.id.desc())
            .limit(limit)
        ).all()
    )
    return [_serialize_job_log(item) for item in logs]


def _get_target_athletes(db: Session, settings: Settings, *, athlete_id: int | None) -> list[Athlete]:
    del settings
    if athlete_id is not None:
        athlete = db.get(Athlete, athlete_id)
        if athlete is None or athlete.status != "active":
            return []
        return [athlete]

    athletes = list(
        db.scalars(
            select(Athlete)
            .where(Athlete.status == "active")
            .options(selectinload(Athlete.garmin_accounts))
            .order_by(Athlete.id.asc())
        ).all()
    )
    return athletes


def _get_active_garmin_account(db: Session, athlete_id: int) -> GarminAccount | None:
    return db.scalar(
        select(GarminAccount)
        .where(
            GarminAccount.athlete_id == athlete_id,
            GarminAccount.status == "active",
        )
        .order_by(GarminAccount.id.asc())
    )


def _date_range(start_date: date, end_date: date) -> list[date]:
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    current = start_date
    values: list[date] = []
    while current <= end_date:
        values.append(current)
        current += timedelta(days=1)
    return values


def _infer_activity_sync_start_date(db: Session, athlete_id: int, reference_date: date, *, force: bool) -> date:
    if force:
        return reference_date - timedelta(days=30)
    latest = db.scalar(
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.start_time.is_not(None),
        )
        .order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc())
        .limit(1)
    )
    if latest is None or latest.start_time is None:
        return reference_date - timedelta(days=30)
    return _to_local_datetime(latest.start_time).date()


def _list_activities_for_window(db: Session, *, athlete_id: int, date_from: date, date_to: date) -> list[GarminActivity]:
    athlete = db.get(Athlete, athlete_id)
    start_dt, end_dt = local_date_range_utc_bounds(
        date_from,
        date_to,
        athlete=athlete,
        days_before=1,
        days_after=1,
    )
    statement = (
        select(GarminActivity)
        .where(
            GarminActivity.athlete_id == athlete_id,
            GarminActivity.start_time.is_not(None),
            GarminActivity.start_time >= start_dt,
            GarminActivity.start_time < end_dt,
        )
        .options(
            selectinload(GarminActivity.activity_match),
            selectinload(GarminActivity.session_analyses),
        )
        .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
    )
    activities = list(db.scalars(statement).all())
    return [
        activity
        for activity in activities
        if date_from <= _to_local_datetime(activity.start_time).date() <= date_to
    ]


def _activity_needs_analysis(activity: GarminActivity) -> bool:
    completed = [
        analysis
        for analysis in activity.session_analyses
        if analysis.analysis_version == SESSION_ANALYSIS_VERSION and analysis.status.startswith("completed")
    ]
    if not completed:
        return True
    latest = max(
        completed,
        key=lambda item: (_to_aware(item.analyzed_at) if item.analyzed_at else datetime.min.replace(tzinfo=timezone.utc), item.id),
    )
    if latest.analyzed_at is None:
        return True
    activity_updated = _to_aware(activity.updated_at)
    analysis_time = _to_aware(latest.analyzed_at)
    return analysis_time < activity_updated


def _recalculate_readiness(db: Session, athlete_id: int, reference_date: date) -> None:
    # Trigger the current evaluation pipeline to ensure the data window is valid after sync.
    summary = build_health_readiness_summary(db, athlete_id, reference_date)
    evaluate_health_readiness(summary)


def _find_blocking_running_job(db: Session, job_type: str, *, now: datetime) -> ScheduledSyncJobLog | None:
    running_jobs = list(
        db.scalars(
            select(ScheduledSyncJobLog)
            .where(
                ScheduledSyncJobLog.job_type == job_type,
                ScheduledSyncJobLog.status == "running",
                ScheduledSyncJobLog.athlete_id.is_(None),
            )
            .order_by(ScheduledSyncJobLog.started_at.desc(), ScheduledSyncJobLog.id.desc())
        ).all()
    )
    recent_before = now - timedelta(minutes=JOB_LOCK_MINUTES)
    for job in running_jobs:
        if _to_aware(job.started_at) <= recent_before:
            continue
        return job
    return None


def _build_stale_note(db: Session, job_type: str, now: datetime) -> str | None:
    running_jobs = list(
        db.scalars(
            select(ScheduledSyncJobLog)
            .where(
                ScheduledSyncJobLog.job_type == job_type,
                ScheduledSyncJobLog.status == "running",
                ScheduledSyncJobLog.athlete_id.is_(None),
            )
            .order_by(ScheduledSyncJobLog.started_at.desc(), ScheduledSyncJobLog.id.desc())
        ).all()
    )
    stale_before = now - timedelta(hours=JOB_STALE_HOURS)
    for job in running_jobs:
        if _to_aware(job.started_at) <= stale_before:
            return f"Se detecto un job running stale previo (#{job.id}) y se permitio continuar."
    return None


def _create_running_log(db: Session, job_type: str, started_at: datetime, *, message: str) -> ScheduledSyncJobLog:
    log = ScheduledSyncJobLog(
        athlete_id=None,
        job_type=job_type,
        started_at=started_at,
        status="running",
        message=message,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def _create_skipped_log(
    db: Session,
    job_type: str,
    blocking_job: ScheduledSyncJobLog,
    *,
    now: datetime,
) -> ScheduledSyncJobLog:
    age_minutes = int(round((now - _to_aware(blocking_job.started_at)).total_seconds() / 60.0))
    message = (
        f"Ya existe un job en ejecucion. Se omitio {job_type}: corrida running iniciada hace "
        f"{age_minutes} minutos (job #{blocking_job.id})."
    )
    log = ScheduledSyncJobLog(
        athlete_id=None,
        job_type=job_type,
        started_at=now,
        finished_at=now,
        status="skipped",
        message=message,
        error_detail=message,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def _finalize_job_log(
    db: Session,
    log: ScheduledSyncJobLog,
    summary: ScheduledJobRunSummary,
) -> ScheduledJobRunSummary:
    finished_at = summary.finished_at or utc_now()
    log.finished_at = finished_at
    log.status = summary.status
    log.message = summary.message
    log.activities_created = summary.activities_created
    log.activities_updated = summary.activities_updated
    log.activities_linked = summary.activities_linked
    log.activity_analyses_created = summary.activity_analyses_created
    log.health_days_synced = summary.health_days_synced
    log.health_ai_analyses_created = summary.health_ai_analyses_created
    log.weekly_analyses_created = summary.weekly_analyses_created
    log.pending_items_created = summary.pending_items_created
    log.pending_items_resolved = summary.pending_items_resolved
    log.error_detail = summary.error_detail
    db.add(log)
    db.commit()
    db.refresh(log)
    summary.finished_at = finished_at
    summary.log_id = log.id
    return summary


def _resolve_summary_status(summary: ScheduledJobRunSummary, athlete_errors: list[str]) -> str:
    if summary.athletes_processed == 0:
        return "skipped"
    if summary.athletes_succeeded == 0 and summary.athletes_failed == 0 and summary.athletes_skipped > 0:
        return "skipped"
    if summary.athletes_failed == 0:
        return "success"
    if summary.athletes_succeeded > 0:
        return "partial_success"
    if athlete_errors:
        return "failed"
    return "success"


def _build_summary_message(summary: ScheduledJobRunSummary) -> str:
    parts = [
        f"{summary.athletes_succeeded}/{summary.athletes_processed} atletas ok",
    ]
    if summary.athletes_skipped:
        skipped_label = "omitido sin Garmin" if summary.athletes_skipped == 1 else "omitidos sin Garmin"
        parts.append(f"{summary.athletes_skipped} {skipped_label}")
    parts.append(f"salud {summary.health_days_synced} dias")
    if summary.job_type == JOB_TYPE_EVENING_FULL:
        parts.extend(
            [
                f"actividades +{summary.activities_created}",
                f"actualizadas {summary.activities_updated}",
                f"vinculadas {summary.activities_linked}",
                f"analisis {summary.activity_analyses_created}",
                f"semanales {summary.weekly_analyses_created}",
            ]
        )
    elif summary.job_type == JOB_TYPE_RESOLVE_PENDING:
        parts.extend(
            [
                f"pendientes creados {summary.pending_items_created}",
                f"pendientes resueltos {summary.pending_items_resolved}",
            ]
        )
    else:
        parts.append(f"health AI {summary.health_ai_analyses_created}")
    if summary.athletes_failed:
        parts.append(f"fallaron {summary.athletes_failed}")
    return " | ".join(parts)


def _athlete_error_message(athlete: Athlete, results: list[SyncOperationResult]) -> str:
    errors = [item.error_detail or item.message for item in results if item.status == "failed"]
    partials = [item.message for item in results if item.status == "partial_success"]
    detail = "; ".join(errors or partials)
    return f"{athlete.name}: {detail}" if detail else f"{athlete.name}: fallo sin detalle."


def _latest_job_log(db: Session, job_type: str) -> ScheduledSyncJobLog | None:
    return db.scalar(
        select(ScheduledSyncJobLog)
        .where(
            ScheduledSyncJobLog.job_type == job_type,
            ScheduledSyncJobLog.athlete_id.is_(None),
        )
        .order_by(ScheduledSyncJobLog.started_at.desc(), ScheduledSyncJobLog.id.desc())
    )


def _serialize_job_log(log: ScheduledSyncJobLog | None) -> dict[str, Any] | None:
    if log is None:
        return None
    return {
        "id": log.id,
        "job_type": log.job_type,
        "status": log.status,
        "message": log.message or "-",
        "started_at": log.started_at.isoformat() if log.started_at else None,
        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
        "started_at_label": _format_datetime_label(log.started_at),
        "finished_at_label": _format_datetime_label(log.finished_at),
        "counts_label": _format_counts_label(log),
        "activities_created": log.activities_created,
        "activities_updated": log.activities_updated,
        "activities_linked": log.activities_linked,
        "activity_analyses_created": log.activity_analyses_created,
        "health_days_synced": log.health_days_synced,
        "health_ai_analyses_created": log.health_ai_analyses_created,
        "weekly_analyses_created": log.weekly_analyses_created,
        "pending_items_created": log.pending_items_created,
        "pending_items_resolved": log.pending_items_resolved,
    }


def _format_datetime_label(value: datetime | None) -> str:
    if value is None:
        return "-"
    return _to_local_datetime(value).strftime("%d/%m/%Y %H:%M")


def _format_counts_label(log: ScheduledSyncJobLog) -> str:
    parts: list[str] = []
    if log.health_days_synced:
        parts.append(f"salud {log.health_days_synced} d")
    if log.health_ai_analyses_created:
        parts.append(f"IA salud {log.health_ai_analyses_created}")
    if log.activities_created:
        parts.append(f"+{log.activities_created} act")
    if log.activities_updated:
        parts.append(f"{log.activities_updated} act actualizadas")
    if log.activities_linked:
        parts.append(f"{log.activities_linked} vinculadas")
    if log.activity_analyses_created:
        parts.append(f"{log.activity_analyses_created} analisis")
    if log.weekly_analyses_created:
        parts.append(f"{log.weekly_analyses_created} semanal")
    if log.pending_items_created:
        parts.append(f"{log.pending_items_created} pendientes nuevos")
    if log.pending_items_resolved:
        parts.append(f"{log.pending_items_resolved} pendientes resueltos")
    return " | ".join(parts) if parts else "Sin contadores relevantes."


def _to_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _to_local_datetime(value: datetime) -> datetime:
    local_value = to_local_datetime(value)
    if local_value is None:
        return _to_aware(value)
    return local_value


@dataclass(slots=True)
class _GarminSyncPreparation:
    athlete: Athlete | None
    account: GarminAccount | None
    credentials: GarminCredentialBundle | None
    skip_result: SyncOperationResult | None = None
    failed_result: SyncOperationResult | None = None


def _prepare_garmin_sync(db: Session, settings: Settings, athlete_id: int) -> _GarminSyncPreparation:
    athlete = _get_sync_athlete(db, athlete_id=athlete_id)
    account = _get_active_garmin_account(db, athlete.id)
    try:
        credentials = resolve_garmin_credentials(settings, athlete, account)
    except (GarminCredentialConfigurationError, GarminCredentialDecryptError) as exc:
        return _GarminSyncPreparation(
            athlete=athlete,
            account=account,
            credentials=None,
            failed_result=SyncOperationResult(
                status="failed",
                message=str(exc),
                error_detail="invalid_garmin_credentials",
            ),
        )

    if credentials is None:
        return _GarminSyncPreparation(
            athlete=athlete,
            account=account,
            credentials=None,
            skip_result=SyncOperationResult(
                status="skipped",
                message="Atleta sin Garmin configurado",
            ),
        )

    prepared_account = account or get_or_create_garmin_account(db, athlete)
    desired_token_dir = credentials.token_dir or default_token_dir_for_athlete(athlete.id)
    if prepared_account.token_dir != desired_token_dir or not prepared_account.garmin_email:
        prepared_account.token_dir = desired_token_dir
        prepared_account.garmin_email = prepared_account.garmin_email or credentials.email
        db.add(prepared_account)
        db.commit()
        db.refresh(prepared_account)

    return _GarminSyncPreparation(
        athlete=athlete,
        account=prepared_account,
        credentials=credentials,
    )


def _is_missing_garmin_skip(result: SyncOperationResult) -> bool:
    return result.status == "skipped" and result.message == "Atleta sin Garmin configurado"
