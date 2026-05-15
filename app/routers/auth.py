from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.db.session import get_db
from app.services.auth_context import auth_is_bootstrapped, clear_login_session, get_current_user, login_user
from app.services.security import verify_password
from app.services.user_permission_service import list_accessible_athletes
from app.web.templates import build_templates


router = APIRouter(tags=["auth"])
templates = build_templates(Path(__file__).resolve().parent.parent)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    if auth_is_bootstrapped(db):
        user = get_current_user(request, db)
        if user is not None:
            return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "error_message": request.query_params.get("error"),
            "bootstrap_mode": not auth_is_bootstrapped(db),
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return RedirectResponse(url="/login?error=Credenciales%20inv%C3%A1lidas", status_code=303)

    login_user(request, user)
    accessible_athletes = list_accessible_athletes(db, user, only_active=True)
    if len(accessible_athletes) == 1:
        return RedirectResponse(url=f"/dashboard?athlete_id={accessible_athletes[0].id}", status_code=303)
    return RedirectResponse(url="/athletes/select", status_code=303)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    clear_login_session(request)
    return RedirectResponse(url="/login", status_code=303)
