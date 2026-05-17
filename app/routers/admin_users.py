from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.athlete import Athlete
from app.db.models.user import User
from app.db.models.user_athlete_permission import UserAthletePermission
from app.db.session import get_db
from app.services.auth_context import require_admin_user
from app.services.security import hash_password
from app.services.user_permission_service import USER_ROLES, normalize_permission_role
from app.web.templates import build_templates


router = APIRouter(prefix="/admin/users", tags=["admin-users"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _require_admin(request: Request, db: Session) -> User:
    return require_admin_user(request, db)


def _redirect(url: str, *, status_message: str | None = None, error_message: str | None = None) -> RedirectResponse:
    params: list[str] = []
    if status_message:
        params.append(f"status_message={quote(status_message)}")
    if error_message:
        params.append(f"error={quote(error_message)}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(url=f"{url}{suffix}", status_code=303)


def _list_athletes(db: Session) -> list[Athlete]:
    return list(db.scalars(select(Athlete).order_by(Athlete.name.asc(), Athlete.id.asc())).all())


def _list_users_with_permissions(db: Session) -> list[User]:
    statement = (
        select(User)
        .options(selectinload(User.athlete_permissions).selectinload(UserAthletePermission.athlete))
        .order_by(User.name.asc(), User.id.asc())
    )
    return list(db.scalars(statement).all())


def _list_athlete_permission_rows(db: Session) -> list[Athlete]:
    statement = (
        select(Athlete)
        .options(
            selectinload(Athlete.user_permissions).selectinload(UserAthletePermission.user),
        )
        .order_by(Athlete.name.asc(), Athlete.id.asc())
    )
    return list(db.scalars(statement).all())


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.scalar(
        select(User)
        .options(selectinload(User.athlete_permissions).selectinload(UserAthletePermission.athlete))
        .where(User.id == user_id)
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    return user


def _get_permission_or_404(db: Session, user_id: int, permission_id: int) -> UserAthletePermission:
    permission = db.scalar(
        select(UserAthletePermission)
        .options(selectinload(UserAthletePermission.athlete))
        .where(
            UserAthletePermission.id == permission_id,
            UserAthletePermission.user_id == user_id,
        )
    )
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permiso no encontrado.")
    return permission


def _normalize_role(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in USER_ROLES:
        raise ValueError("El rol seleccionado no es valido.")
    return normalized


def _normalize_email(value: str) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        raise ValueError("El email es obligatorio.")
    return normalized


def _normalize_name(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError("El nombre es obligatorio.")
    return normalized


def _ensure_unique_email(db: Session, email: str, *, exclude_user_id: int | None = None) -> None:
    statement = select(func.count(User.id)).where(User.email == email)
    if exclude_user_id is not None:
        statement = statement.where(User.id != exclude_user_id)
    if db.scalar(statement):
        raise ValueError("Ya existe un usuario con ese email.")


def _coerce_optional_athlete(db: Session, athlete_id: int | None) -> Athlete | None:
    if athlete_id in (None, 0):
        return None
    athlete = db.get(Athlete, athlete_id)
    if athlete is None:
        raise ValueError("El atleta seleccionado no existe.")
    return athlete


def _build_permission(
    *,
    user_id: int,
    athlete_id: int,
    permission_role: str,
    can_view: bool,
    can_edit: bool,
    can_sync_garmin: bool,
) -> UserAthletePermission:
    if can_edit or can_sync_garmin:
        can_view = True
    return UserAthletePermission(
        user_id=user_id,
        athlete_id=athlete_id,
        permission_role=normalize_permission_role(permission_role),
        can_view=bool(can_view),
        can_edit=bool(can_edit),
        can_sync_garmin=bool(can_sync_garmin),
    )


@router.get("", response_class=HTMLResponse)
def admin_users_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    _require_admin(request, db)
    return templates.TemplateResponse(
        request=request,
        name="admin/users/index.html",
        context={
            "users": _list_users_with_permissions(db),
            "athletes": _list_athlete_permission_rows(db),
            "status_message": request.query_params.get("status_message"),
            "error_message": request.query_params.get("error"),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def admin_users_new_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    _require_admin(request, db)
    return templates.TemplateResponse(
        request=request,
        name="admin/users/new.html",
        context={
            "athletes": _list_athletes(db),
            "status_message": request.query_params.get("status_message"),
            "error_message": request.query_params.get("error"),
        },
    )


@router.post("/new")
def admin_users_create(
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    is_active: bool = Form(False),
    athlete_id: int | None = Form(default=None),
    permission_role: str = Form(default="owner"),
    can_view: bool = Form(False),
    can_edit: bool = Form(False),
    can_sync_garmin: bool = Form(False),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _require_admin(request, db)
    try:
        normalized_email = _normalize_email(email)
        normalized_name = _normalize_name(name)
        normalized_role = _normalize_role(role)
        if not password.strip():
            raise ValueError("La contraseña inicial es obligatoria.")
        _ensure_unique_email(db, normalized_email)
        athlete = _coerce_optional_athlete(db, athlete_id)
    except ValueError as exc:
        return _redirect("/admin/users/new", error_message=str(exc))

    user = User(
        email=normalized_email,
        name=normalized_name,
        password_hash=hash_password(password),
        role=normalized_role,
        is_active=bool(is_active),
    )
    db.add(user)
    db.flush()
    if athlete is not None:
        db.add(
            _build_permission(
                user_id=user.id,
                athlete_id=athlete.id,
                permission_role=permission_role,
                can_view=can_view,
                can_edit=can_edit,
                can_sync_garmin=can_sync_garmin,
            )
        )
    db.commit()
    return _redirect(f"/admin/users/{user.id}/edit", status_message="Usuario creado correctamente.")


@router.get("/{user_id}/edit", response_class=HTMLResponse)
def admin_users_edit_page(user_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    _require_admin(request, db)
    return templates.TemplateResponse(
        request=request,
        name="admin/users/edit.html",
        context={
            "managed_user": _get_user_or_404(db, user_id),
            "athletes": _list_athletes(db),
            "status_message": request.query_params.get("status_message"),
            "error_message": request.query_params.get("error"),
        },
    )


@router.post("/{user_id}/edit")
def admin_users_edit(
    user_id: int,
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    role: str = Form(...),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _require_admin(request, db)
    user = _get_user_or_404(db, user_id)
    try:
        normalized_email = _normalize_email(email)
        normalized_name = _normalize_name(name)
        normalized_role = _normalize_role(role)
        _ensure_unique_email(db, normalized_email, exclude_user_id=user.id)
    except ValueError as exc:
        return _redirect(f"/admin/users/{user.id}/edit", error_message=str(exc))

    user.email = normalized_email
    user.name = normalized_name
    user.role = normalized_role
    user.is_active = bool(is_active)
    db.commit()
    return _redirect(f"/admin/users/{user.id}/edit", status_message="Usuario actualizado.")


@router.get("/{user_id}/reset-password", response_class=HTMLResponse)
def admin_users_reset_password_page(user_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    _require_admin(request, db)
    return templates.TemplateResponse(
        request=request,
        name="admin/users/reset_password.html",
        context={
            "managed_user": _get_user_or_404(db, user_id),
            "status_message": request.query_params.get("status_message"),
            "error_message": request.query_params.get("error"),
        },
    )


@router.post("/{user_id}/reset-password")
def admin_users_reset_password(
    user_id: int,
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _require_admin(request, db)
    user = _get_user_or_404(db, user_id)
    if not new_password.strip():
        return _redirect(f"/admin/users/{user.id}/reset-password", error_message="La nueva contraseña es obligatoria.")
    if new_password != confirm_password:
        return _redirect(f"/admin/users/{user.id}/reset-password", error_message="Las contraseñas no coinciden.")
    user.password_hash = hash_password(new_password)
    db.commit()
    return _redirect(f"/admin/users/{user.id}/edit", status_message="Contraseña actualizada.")


@router.post("/{user_id}/deactivate")
def admin_users_deactivate(user_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    _require_admin(request, db)
    user = _get_user_or_404(db, user_id)
    user.is_active = False
    db.commit()
    return _redirect("/admin/users", status_message="Usuario desactivado.")


@router.post("/{user_id}/activate")
def admin_users_activate(user_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    _require_admin(request, db)
    user = _get_user_or_404(db, user_id)
    user.is_active = True
    db.commit()
    return _redirect("/admin/users", status_message="Usuario activado.")


@router.post("/{user_id}/delete")
def admin_users_delete(user_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    _require_admin(request, db)
    user = _get_user_or_404(db, user_id)
    user.is_active = False
    db.commit()
    return _redirect("/admin/users", status_message="Usuario desactivado. No se eliminó información histórica.")


@router.post("/{user_id}/permissions/add")
def admin_users_add_permission(
    user_id: int,
    request: Request,
    athlete_id: int = Form(...),
    permission_role: str = Form(default="viewer"),
    can_view: bool = Form(False),
    can_edit: bool = Form(False),
    can_sync_garmin: bool = Form(False),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _require_admin(request, db)
    user = _get_user_or_404(db, user_id)
    try:
        athlete = _coerce_optional_athlete(db, athlete_id)
        if athlete is None:
            raise ValueError("Debes seleccionar un atleta.")
        duplicate = db.scalar(
            select(UserAthletePermission).where(
                UserAthletePermission.user_id == user.id,
                UserAthletePermission.athlete_id == athlete.id,
            )
        )
        if duplicate is not None:
            raise ValueError("Ese usuario ya tiene un permiso asignado para este atleta.")
    except ValueError as exc:
        return _redirect(f"/admin/users/{user.id}/edit", error_message=str(exc))

    db.add(
        _build_permission(
            user_id=user.id,
            athlete_id=athlete.id,
            permission_role=permission_role,
            can_view=can_view,
            can_edit=can_edit,
            can_sync_garmin=can_sync_garmin,
        )
    )
    db.commit()
    return _redirect(f"/admin/users/{user.id}/edit", status_message="Permiso agregado.")


@router.post("/{user_id}/permissions/{permission_id}/edit")
def admin_users_edit_permission(
    user_id: int,
    permission_id: int,
    request: Request,
    permission_role: str = Form(...),
    can_view: bool = Form(False),
    can_edit: bool = Form(False),
    can_sync_garmin: bool = Form(False),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _require_admin(request, db)
    _get_user_or_404(db, user_id)
    permission = _get_permission_or_404(db, user_id, permission_id)
    permission.permission_role = normalize_permission_role(permission_role)
    permission.can_view = bool(can_view or can_edit or can_sync_garmin)
    permission.can_edit = bool(can_edit)
    permission.can_sync_garmin = bool(can_sync_garmin)
    db.commit()
    return _redirect(f"/admin/users/{user_id}/edit", status_message="Permiso actualizado.")


@router.post("/{user_id}/permissions/{permission_id}/delete")
def admin_users_delete_permission(
    user_id: int,
    permission_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _require_admin(request, db)
    _get_user_or_404(db, user_id)
    permission = _get_permission_or_404(db, user_id, permission_id)
    db.delete(permission)
    db.commit()
    return _redirect(f"/admin/users/{user_id}/edit", status_message="Permiso eliminado.")
