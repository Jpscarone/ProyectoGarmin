from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.garmin_account import GarminAccount
from app.db.models.health_sync_state import HealthSyncState
from app.db.session import get_db
from app.services.activity_matching_service import match_recent_activities
from app.services.activity_auto_sync_service import run_activity_auto_sync
from app.services.athlete_context import get_current_athlete
from app.services.garmin.activity_sync import GarminSyncResult, sync_recent_activities
from app.services.garmin.auth import (
    GarminMFARequired,
    GarminServiceError,
    get_garmin_auth_diagnostics,
    has_pending_mfa,
)
from app.services.garmin.health_sync import GarminHealthSyncResult, sync_recent_health
from app.services.weather.weather_service import BatchWeatherSyncResult, sync_weather_for_recent_activities
from app.web.templates import build_templates


router = APIRouter(prefix="/sync/garmin", tags=["garmin_sync"])
templates = build_templates(Path(__file__).resolve().parent.parent)


@dataclass
class SyncAllResult:
    activities: GarminSyncResult
    health: GarminHealthSyncResult
    weather: BatchWeatherSyncResult
    match_summary: str


@dataclass
class GarminSyncOverview:
    activity_last_sync_at: str
    activity_status: str
    activity_message: str
    health_last_sync_at: str
    health_status: str
    health_message: str
    full_last_sync_at: str
    full_status: str
    full_message: str
    latest_sync_at: str
    latest_sync_status: str
    latest_sync_message: str
    latest_sync_label: str
    last_connection_success_at: str


def _sync_activities_and_redirect(*, request: Request, success_url: str, error_url: str, db: Session) -> RedirectResponse:
    settings = get_settings()

    try:
        athlete = get_current_athlete(request, db, require_selected=True)
        payload = run_activity_auto_sync(
            db,
            athlete=athlete,
            settings=settings,
            force=True,
        )
        message = str(payload["message"])
        return RedirectResponse(url=f"{success_url}{quote(message)}", status_code=303)
    except GarminMFARequired as exc:
        return RedirectResponse(url=f"{error_url}{quote(str(exc))}", status_code=303)
    except GarminServiceError as exc:
        return RedirectResponse(url=f"{error_url}{quote(str(exc))}", status_code=303)
    except Exception as exc:
        return RedirectResponse(
            url=f"{error_url}{quote(f'La sincronizacion Garmin fallo de forma inesperada: {exc}')}",
            status_code=303,
        )


def _format_datetime_label(value: datetime | None) -> str:
    if value is None:
        return "-"
    current = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return current.astimezone().strftime("%d/%m/%Y %H:%M")


def _garmin_account_for_athlete(db: Session, athlete_id: int | None) -> GarminAccount | None:
    if athlete_id is None:
        return None
    return db.scalar(
        select(GarminAccount)
        .where(GarminAccount.athlete_id == athlete_id)
        .order_by(GarminAccount.id.asc())
        .limit(1)
    )


def _health_sync_state_for_athlete(db: Session, athlete_id: int | None) -> HealthSyncState | None:
    if athlete_id is None:
        return None
    return db.scalar(
        select(HealthSyncState)
        .where(
            HealthSyncState.athlete_id == athlete_id,
            HealthSyncState.source == "garmin",
        )
        .order_by(HealthSyncState.updated_at.desc(), HealthSyncState.id.desc())
        .limit(1)
    )


def _build_sync_overview(
    *,
    account: GarminAccount | None,
    health_state: HealthSyncState | None,
    profile_last_synced_at: datetime | None,
) -> GarminSyncOverview:
    activity_at = account.last_activity_sync_at if account is not None else None
    activity_status = account.last_activity_sync_status if account and account.last_activity_sync_status else "sin datos"
    activity_message = account.last_activity_sync_message if account and account.last_activity_sync_message else "-"

    health_at = health_state.last_success_at if health_state is not None else None
    health_status = health_state.status if health_state and health_state.status else "sin datos"
    if health_state is None:
        health_message = "-"
    elif health_state.error_message:
        health_message = health_state.error_message
    else:
        created = health_state.records_created or 0
        updated = health_state.records_updated or 0
        health_message = f"Creados {created}, actualizados {updated}."

    full_at: datetime | None = None
    full_status = "sin datos"
    full_message = "-"
    if activity_at is not None and health_at is not None:
        full_at = min(activity_at, health_at)
        if activity_status == "success" and health_status == "success":
            full_status = "success"
            full_message = "Actividades y salud tienen una sincronizacion exitosa registrada."
        elif activity_status == "error" or health_status == "error":
            full_status = "error"
            full_message = "La ultima sincronizacion completa conocida quedo incompleta por error en alguno de los bloques."
        else:
            full_status = "parcial"
            full_message = "Hay sincronizaciones registradas, pero no ambas figuran como exitosas."

    latest_events = [
        ("actividades", activity_at, activity_status, activity_message),
        ("salud", health_at, health_status, health_message),
    ]
    latest_label = "-"
    latest_at = None
    latest_status = "sin datos"
    latest_message = "-"
    for label, event_at, event_status, event_message in latest_events:
        if event_at is None:
            continue
        if latest_at is None or event_at > latest_at:
            latest_label = label
            latest_at = event_at
            latest_status = event_status
            latest_message = event_message

    connection_candidates = [value for value in (activity_at, health_at, profile_last_synced_at) if value is not None]
    last_connection_success_at = max(connection_candidates) if connection_candidates else None

    return GarminSyncOverview(
        activity_last_sync_at=_format_datetime_label(activity_at),
        activity_status=activity_status,
        activity_message=activity_message,
        health_last_sync_at=_format_datetime_label(health_at),
        health_status=health_status,
        health_message=health_message,
        full_last_sync_at=_format_datetime_label(full_at),
        full_status=full_status,
        full_message=full_message,
        latest_sync_at=_format_datetime_label(latest_at),
        latest_sync_status=latest_status,
        latest_sync_message=latest_message,
        latest_sync_label=latest_label,
        last_connection_success_at=_format_datetime_label(last_connection_success_at),
    )


def _build_page_context(
    *,
    request: Request,
    db: Session,
    garmin_enabled: bool,
    result: GarminSyncResult | None,
    sync_all_result: SyncAllResult | None,
    error: str | None,
    status_message: str | None,
    selected_athlete,
) -> dict[str, object]:
    settings = get_settings()
    diagnostics = get_garmin_auth_diagnostics(settings)
    athlete_id = selected_athlete.id if selected_athlete is not None else None
    account = _garmin_account_for_athlete(db, athlete_id)
    health_state = _health_sync_state_for_athlete(db, athlete_id)
    sync_overview = _build_sync_overview(
        account=account,
        health_state=health_state,
        profile_last_synced_at=getattr(selected_athlete, "garmin_profile_last_synced_at", None),
    )
    return {
        "garmin_enabled": garmin_enabled,
        "result": result,
        "sync_all_result": sync_all_result,
        "error": error,
        "status_message": status_message,
        "needs_mfa": has_pending_mfa(settings),
        "garmin_auth_diagnostics": diagnostics,
        "selected_athlete": selected_athlete,
        "sync_overview": sync_overview,
    }


@router.get("/activities", response_class=HTMLResponse)
def sync_garmin_activities_page(request: Request, athlete_id: int | None = None, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_activities.html",
        context=_build_page_context(
            request=request,
            db=db,
            garmin_enabled=settings.garmin_enabled,
            result=None,
            sync_all_result=None,
            error=None,
            status_message=request.query_params.get("status"),
            selected_athlete=athlete,
        ),
    )


@router.post("/activities", response_class=HTMLResponse)
def sync_garmin_activities(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    result: GarminSyncResult | None = None
    error: str | None = None

    try:
        athlete = get_current_athlete(request, db, require_selected=True)
        payload = run_activity_auto_sync(
            db,
            athlete=athlete,
            settings=settings,
            force=True,
        )
        result = payload["sync_result"]
        if not payload["synced"]:
            error = str(payload["message"])
    except GarminMFARequired as exc:
        error = str(exc)
    except GarminServiceError as exc:
        error = str(exc)
    except Exception as exc:
        error = f"La sincronizacion Garmin fallo de forma inesperada: {exc}"

    athlete = get_current_athlete(request, db)
    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_activities.html",
        context=_build_page_context(
            request=request,
            db=db,
            garmin_enabled=settings.garmin_enabled,
            result=result,
            sync_all_result=None,
            error=error,
            status_message=None,
            selected_athlete=athlete,
        ),
    )


@router.post("/activities/mfa", response_class=HTMLResponse)
def sync_garmin_activities_mfa(
    request: Request,
    mfa_code: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    settings = get_settings()
    result: GarminSyncResult | None = None
    error: str | None = None

    try:
        athlete = get_current_athlete(request, db, require_selected=True)
        payload = run_activity_auto_sync(
            db,
            athlete=athlete,
            settings=settings,
            force=True,
            mfa_code=mfa_code,
        )
        result = payload["sync_result"]
        if not payload["synced"]:
            error = str(payload["message"])
    except GarminMFARequired as exc:
        error = str(exc)
    except GarminServiceError as exc:
        error = str(exc)
    except Exception as exc:
        error = f"La sincronizacion Garmin fallo de forma inesperada: {exc}"

    athlete = get_current_athlete(request, db)
    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_activities.html",
        context=_build_page_context(
            request=request,
            db=db,
            garmin_enabled=settings.garmin_enabled,
            result=result,
            sync_all_result=None,
            error=error,
            status_message=None,
            selected_athlete=athlete,
        ),
    )


@router.post("/all", response_class=HTMLResponse)
def sync_everything(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    sync_all_result: SyncAllResult | None = None
    error: str | None = None

    try:
        athlete = get_current_athlete(request, db, require_selected=True)
        activity_result = sync_recent_activities(db, settings, athlete_id=athlete.id if athlete else None)
        health_result = sync_recent_health(db, settings, athlete_id=athlete.id if athlete else None)
        weather_result = sync_weather_for_recent_activities(db, limit=20, only_missing=True)
        match_result = match_recent_activities(db)
        sync_all_result = SyncAllResult(
            activities=activity_result,
            health=health_result,
            weather=weather_result,
            match_summary=(
                f"Vinculacion reciente: {match_result.processed} revisadas, "
                f"{match_result.matched} vinculadas, {match_result.unmatched} sin vincular."
            ),
        )
    except GarminMFARequired as exc:
        error = str(exc)
    except GarminServiceError as exc:
        error = str(exc)
    except Exception as exc:
        error = f"La sincronizacion completa fallo de forma inesperada: {exc}"

    athlete = get_current_athlete(request, db)
    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_activities.html",
        context=_build_page_context(
            request=request,
            db=db,
            garmin_enabled=settings.garmin_enabled,
            result=None,
            sync_all_result=sync_all_result,
            error=error,
            status_message=None,
            selected_athlete=athlete,
        ),
    )


@router.post("/activities/from-list")
def sync_garmin_activities_from_list(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    return _sync_activities_and_redirect(
        request=request,
        success_url="/activities?ui_status=",
        error_url="/activities?ui_status=",
        db=db,
    )
