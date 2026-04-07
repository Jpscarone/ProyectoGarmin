from __future__ import annotations

from pathlib import Path

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.services.garmin.auth import (
    GarminMFARequired,
    GarminServiceError,
    get_garmin_auth_diagnostics,
    has_pending_mfa,
)
from app.services.garmin.health_sync import GarminHealthSyncResult, sync_recent_health
from app.web.templates import build_templates


router = APIRouter(prefix="/sync/garmin", tags=["garmin_health_sync"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _sync_health_and_redirect(*, success_url: str, error_url: str, db: Session) -> RedirectResponse:
    settings = get_settings()

    try:
        result = sync_recent_health(db, settings)
        message = (
            f"Salud sincronizada. Dias revisados: {result.days_reviewed}, "
            f"creados: {result.created}, actualizados: {result.updated}."
        )
        return RedirectResponse(url=f"{success_url}{quote(message)}", status_code=303)
    except GarminMFARequired as exc:
        return RedirectResponse(url=f"{error_url}{quote(str(exc))}", status_code=303)
    except GarminServiceError as exc:
        return RedirectResponse(url=f"{error_url}{quote(str(exc))}", status_code=303)
    except Exception as exc:
        return RedirectResponse(
            url=f"{error_url}{quote(f'La sincronizacion de salud Garmin fallo de forma inesperada: {exc}')}",
            status_code=303,
        )


@router.get("/health", response_class=HTMLResponse)
def sync_garmin_health_page(request: Request) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_health.html",
        context={
            "garmin_enabled": settings.garmin_enabled,
            "result": None,
            "error": None,
            "needs_mfa": has_pending_mfa(settings),
            "garmin_auth_diagnostics": get_garmin_auth_diagnostics(settings),
        },
    )


@router.post("/health", response_class=HTMLResponse)
def sync_garmin_health(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    result: GarminHealthSyncResult | None = None
    error: str | None = None

    try:
        result = sync_recent_health(db, settings)
    except GarminMFARequired as exc:
        error = str(exc)
    except GarminServiceError as exc:
        error = str(exc)
    except Exception as exc:
        error = f"La sincronizacion de salud Garmin fallo de forma inesperada: {exc}"

    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_health.html",
        context={
            "garmin_enabled": settings.garmin_enabled,
            "result": result,
            "error": error,
            "needs_mfa": has_pending_mfa(settings),
            "garmin_auth_diagnostics": get_garmin_auth_diagnostics(settings),
        },
    )


@router.post("/health/mfa", response_class=HTMLResponse)
def sync_garmin_health_mfa(
    request: Request,
    mfa_code: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    settings = get_settings()
    result: GarminHealthSyncResult | None = None
    error: str | None = None

    try:
        result = sync_recent_health(db, settings, mfa_code=mfa_code)
    except GarminMFARequired as exc:
        error = str(exc)
    except GarminServiceError as exc:
        error = str(exc)
    except Exception as exc:
        error = f"La sincronizacion de salud Garmin fallo de forma inesperada: {exc}"

    return templates.TemplateResponse(
        request=request,
        name="sync/garmin_health.html",
        context={
            "garmin_enabled": settings.garmin_enabled,
            "result": result,
            "error": error,
            "needs_mfa": has_pending_mfa(settings),
            "garmin_auth_diagnostics": get_garmin_auth_diagnostics(settings),
        },
    )


@router.post("/health/from-activities")
def sync_garmin_health_from_activities(db: Session = Depends(get_db)) -> RedirectResponse:
    return _sync_health_and_redirect(
        success_url="/health?ui_status=",
        error_url="/sync/garmin/activities?status=",
        db=db,
    )


@router.post("/health/from-health")
def sync_garmin_health_from_health(db: Session = Depends(get_db)) -> RedirectResponse:
    return _sync_health_and_redirect(
        success_url="/health?ui_status=",
        error_url="/health?ui_status=",
        db=db,
    )
