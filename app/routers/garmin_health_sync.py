from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
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
