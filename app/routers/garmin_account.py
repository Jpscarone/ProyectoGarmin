from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.services.auth_context import require_current_user
from app.services.athlete_context import get_current_athlete
from app.services.garmin_credential_service import (
    GarminCredentialConfigurationError,
    GarminCredentialDecryptError,
    encrypt_garmin_password,
    get_or_create_garmin_account,
)
from app.services.user_permission_service import require_permission_for_athlete
from app.web.templates import build_templates


router = APIRouter(prefix="/garmin", tags=["garmin_account"])
templates = build_templates(Path(__file__).resolve().parent.parent)


@router.get("/account", response_class=HTMLResponse)
def garmin_account_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user = require_current_user(request, db)
    athlete = get_current_athlete(request, db, require_selected=True)
    permission = require_permission_for_athlete(db, user, athlete.id)
    account = get_or_create_garmin_account(db, athlete)
    can_manage = permission.can_sync_garmin
    password_exists = bool(account.garmin_password_encrypted)
    error_message = request.query_params.get("error")
    if password_exists:
        try:
            if account.garmin_password_encrypted:
                from app.services.garmin_credential_service import decrypt_garmin_password

                decrypt_garmin_password(account.garmin_password_encrypted, get_settings().garmin_credential_secret_key)
        except (GarminCredentialConfigurationError, GarminCredentialDecryptError) as exc:
            error_message = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="garmin/account.html",
        context={
            "athlete": athlete,
            "account": account,
            "can_manage": can_manage,
            "password_exists": password_exists,
            "status_message": request.query_params.get("status"),
            "error_message": error_message,
            "last_sync_at": account.last_sync_at or account.last_activity_sync_at or account.last_health_sync_at,
        },
    )


@router.post("/account")
def garmin_account_submit(
    request: Request,
    garmin_email: str = Form(...),
    garmin_password: str = Form(default=""),
    is_active: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    user = require_current_user(request, db)
    athlete = get_current_athlete(request, db, require_selected=True)
    require_permission_for_athlete(db, user, athlete.id, can_sync_garmin=True)
    account = get_or_create_garmin_account(db, athlete)
    settings = get_settings()

    account.garmin_email = garmin_email.strip() or None
    account.is_active = is_active == "on"
    account.status = "active" if account.is_active else "inactive"
    account.token_dir = account.token_dir or f"var/garmin_tokens/athlete_{athlete.id}"
    if garmin_password.strip():
        try:
            account.garmin_password_encrypted = encrypt_garmin_password(garmin_password.strip(), settings.garmin_credential_secret_key)
        except GarminCredentialConfigurationError as exc:
            return RedirectResponse(url=f"/garmin/account?error={quote(str(exc))}", status_code=303)
    db.add(account)
    db.commit()
    return RedirectResponse(url=f"/garmin/account?status={quote('Cuenta Garmin guardada.')}", status_code=303)
