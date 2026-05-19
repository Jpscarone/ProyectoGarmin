from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.athlete import Athlete
from app.db.models.athlete_access_code import AthleteAccessCode
from app.db.models.user import User
from app.db.models.user_athlete_permission import UserAthletePermission
from app.db.session import get_db
from app.services.athlete_access_code_service import create_athlete_access_code
from app.services.auth_context import require_current_user, require_role
from app.services.user_permission_service import (
    PERMISSION_COACH,
    PERMISSION_OWNER,
    ROLE_ADMIN,
    ROLE_COACH,
    get_permission_for_athlete,
)
from app.web.templates import build_templates


router = APIRouter(prefix="/admin/mcp-access-codes", tags=["admin-mcp-access-codes"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _require_manager(request: Request, db: Session) -> User:
    return require_role(require_current_user(request, db), ROLE_ADMIN, ROLE_COACH)


def _redirect(url: str, *, status_message: str | None = None, error_message: str | None = None) -> RedirectResponse:
    params: list[str] = []
    if status_message:
        params.append(f"status_message={quote(status_message)}")
    if error_message:
        params.append(f"error={quote(error_message)}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(url=f"{url}{suffix}", status_code=303)


def _manageable_athlete_ids(db: Session, user: User) -> list[int]:
    if user.role == ROLE_ADMIN:
        return list(db.scalars(select(Athlete.id).order_by(Athlete.name.asc(), Athlete.id.asc())).all())
    statement = (
        select(UserAthletePermission.athlete_id)
        .where(
            UserAthletePermission.user_id == user.id,
            or_(
                UserAthletePermission.can_edit.is_(True),
                UserAthletePermission.permission_role.in_([PERMISSION_OWNER, PERMISSION_COACH]),
            ),
        )
        .order_by(UserAthletePermission.athlete_id.asc())
    )
    return list(db.scalars(statement).all())


def _list_manageable_athletes(db: Session, user: User) -> list[Athlete]:
    athlete_ids = _manageable_athlete_ids(db, user)
    if not athlete_ids:
        return []
    return list(
        db.scalars(
            select(Athlete)
            .where(Athlete.id.in_(athlete_ids))
            .order_by(Athlete.name.asc(), Athlete.id.asc())
        ).all()
    )


def _require_manageable_athlete(db: Session, user: User, athlete_id: int) -> Athlete:
    athlete = db.get(Athlete, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Atleta no encontrado.")
    if user.role == ROLE_ADMIN:
        return athlete
    permission = get_permission_for_athlete(db, user, athlete_id)
    if permission is None or not permission.can_edit:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para gestionar claves MCP de este atleta.")
    return athlete


def _get_access_code_or_404(db: Session, access_code_id: int) -> AthleteAccessCode:
    row = db.scalar(
        select(AthleteAccessCode)
        .options(selectinload(AthleteAccessCode.athlete))
        .where(AthleteAccessCode.id == access_code_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clave MCP no encontrada.")
    return row


@router.get("", response_class=HTMLResponse)
def list_admin_mcp_access_codes(
    request: Request,
    athlete_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user = _require_manager(request, db)
    manageable_athletes = _list_manageable_athletes(db, user)
    manageable_ids = [athlete.id for athlete in manageable_athletes]
    selected_athlete = None
    if athlete_id is not None:
        selected_athlete = _require_manageable_athlete(db, user, athlete_id)
    if not manageable_ids:
        codes: list[AthleteAccessCode] = []
    else:
        statement = (
            select(AthleteAccessCode)
            .options(selectinload(AthleteAccessCode.athlete))
            .where(AthleteAccessCode.athlete_id.in_(manageable_ids))
            .order_by(AthleteAccessCode.created_at.desc(), AthleteAccessCode.id.desc())
        )
        if selected_athlete is not None:
            statement = statement.where(AthleteAccessCode.athlete_id == selected_athlete.id)
        codes = list(db.scalars(statement).all())
    return templates.TemplateResponse(
        request=request,
        name="admin/mcp_access_codes/index.html",
        context={
            "codes": codes,
            "athletes": manageable_athletes,
            "selected_athlete_id": selected_athlete.id if selected_athlete is not None else None,
            "status_message": request.query_params.get("status_message"),
            "error_message": request.query_params.get("error"),
            "created_code": request.query_params.get("created_code"),
            "created_athlete_name": request.query_params.get("created_athlete_name"),
        },
    )


@router.post("/create")
def create_admin_mcp_access_code(
    request: Request,
    athlete_id: int = Form(...),
    prefix: str | None = Form(default=None),
    label: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    code: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    user = _require_manager(request, db)
    try:
        athlete = _require_manageable_athlete(db, user, athlete_id)
        created = create_athlete_access_code(
            db,
            athlete=athlete,
            label=label,
            code=code,
            prefix=prefix,
            notes=notes,
        )
    except ValueError as exc:
        return _redirect(f"/admin/mcp-access-codes?athlete_id={athlete_id}", error_message=str(exc))

    return RedirectResponse(
        url=(
            f"/admin/mcp-access-codes?athlete_id={athlete.id}"
            f"&status_message={quote('Clave MCP creada.')}"
            f"&created_code={quote(created.access_code)}"
            f"&created_athlete_name={quote(athlete.name)}"
        ),
        status_code=303,
    )


@router.post("/{access_code_id}/deactivate")
def deactivate_admin_mcp_access_code(
    access_code_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    user = _require_manager(request, db)
    row = _get_access_code_or_404(db, access_code_id)
    _require_manageable_athlete(db, user, row.athlete_id)
    row.is_active = False
    db.commit()
    return _redirect(f"/admin/mcp-access-codes?athlete_id={row.athlete_id}", status_message="Clave MCP desactivada.")


@router.post("/{access_code_id}/activate")
def activate_admin_mcp_access_code(
    access_code_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    user = _require_manager(request, db)
    row = _get_access_code_or_404(db, access_code_id)
    _require_manageable_athlete(db, user, row.athlete_id)
    row.is_active = True
    db.commit()
    return _redirect(f"/admin/mcp-access-codes?athlete_id={row.athlete_id}", status_message="Clave MCP reactivada.")
