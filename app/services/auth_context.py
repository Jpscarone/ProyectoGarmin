from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.services.user_permission_service import normalize_user_role


CURRENT_USER_SESSION_KEY = "current_user_id"
CURRENT_ATHLETE_SESSION_KEY = "current_athlete_id"
CURRENT_TRAINING_PLAN_SESSION_KEY = "current_training_plan_id"


def auth_is_bootstrapped(db: Session) -> bool:
    return bool(db.scalar(select(func.count(User.id))))


def get_current_user(request: Request, db: Session) -> User | None:
    raw_user_id = request.session.get(CURRENT_USER_SESSION_KEY)
    if raw_user_id in (None, ""):
        return None
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        request.session.pop(CURRENT_USER_SESSION_KEY, None)
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        clear_login_session(request)
        return None
    user.role = normalize_user_role(user.role)
    return user


def require_current_user(request: Request, db: Session) -> User:
    user = get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Debes iniciar sesión para continuar.")
    return user


def require_role(user: User, *roles: str) -> User:
    if user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para esta acción.")
    return user


def login_user(request: Request, user: User) -> None:
    request.session[CURRENT_USER_SESSION_KEY] = int(user.id)
    request.session.pop(CURRENT_ATHLETE_SESSION_KEY, None)
    request.session.pop(CURRENT_TRAINING_PLAN_SESSION_KEY, None)


def clear_login_session(request: Request) -> None:
    request.session.pop(CURRENT_USER_SESSION_KEY, None)
    request.session.pop(CURRENT_ATHLETE_SESSION_KEY, None)
    request.session.pop(CURRENT_TRAINING_PLAN_SESSION_KEY, None)


def redirect_to_login(next_path: str | None = None) -> RedirectResponse:
    query = f"?next={quote(next_path)}" if next_path else ""
    return RedirectResponse(url=f"/login{query}", status_code=303)
