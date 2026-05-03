from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
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


@router.get("/activities", response_class=HTMLResponse)
def sync_garmin_activities_page(request: Request, athlete_id: int | None = None, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_activities.html",
        context={
            "garmin_enabled": settings.garmin_enabled,
            "result": None,
            "sync_all_result": None,
            "error": None,
            "status_message": request.query_params.get("status"),
            "needs_mfa": has_pending_mfa(settings),
            "garmin_auth_diagnostics": get_garmin_auth_diagnostics(settings),
            "selected_athlete": athlete,
        },
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

    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_activities.html",
        context={
            "garmin_enabled": settings.garmin_enabled,
            "result": result,
            "sync_all_result": None,
            "error": error,
            "status_message": None,
            "needs_mfa": has_pending_mfa(settings),
            "garmin_auth_diagnostics": get_garmin_auth_diagnostics(settings),
        },
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

    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_activities.html",
        context={
            "garmin_enabled": settings.garmin_enabled,
            "result": result,
            "sync_all_result": None,
            "error": error,
            "status_message": None,
            "needs_mfa": has_pending_mfa(settings),
            "garmin_auth_diagnostics": get_garmin_auth_diagnostics(settings),
        },
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

    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_activities.html",
        context={
            "garmin_enabled": settings.garmin_enabled,
            "result": None,
            "sync_all_result": sync_all_result,
            "error": error,
            "status_message": None,
            "needs_mfa": has_pending_mfa(settings),
            "garmin_auth_diagnostics": get_garmin_auth_diagnostics(settings),
        },
    )


@router.post("/activities/from-list")
def sync_garmin_activities_from_list(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    return _sync_activities_and_redirect(
        request=request,
        success_url="/activities?ui_status=",
        error_url="/activities?ui_status=",
        db=db,
    )
