from __future__ import annotations

import re
from datetime import date, time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.planned_session import PlannedSessionCreate, PlannedSessionRead, PlannedSessionUpdate
from app.services.analysis.report_service import get_latest_session_report
from app.services.planning.quick_session_service import (
    SessionAdvancedData,
    create_session_from_quick_mode,
)
from app.services.planned_session_service import (
    create_planned_session,
    delete_planned_session,
    get_planned_session,
    get_planned_sessions,
    update_planned_session,
)
from app.services.session_group_service import create_inline_group
from app.services.training_day_service import create_training_day, get_training_day, get_training_day_by_plan_and_date
from app.services.training_plan_service import get_training_plan
from app.schemas.training_day import TrainingDayCreate
from app.web.templates import build_templates


router = APIRouter(prefix="/planned_sessions", tags=["planned_sessions"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[PlannedSessionRead])
def list_planned_sessions(db: Session = Depends(get_db)) -> list[PlannedSessionRead]:
    return get_planned_sessions(db)


@router.get("/create", response_class=HTMLResponse)
def create_planned_session_page(
    training_day_id: int = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    training_day = get_training_day(db, training_day_id)
    if training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training day not found")
    return RedirectResponse(url=f"/planned_sessions/quick?training_day_id={training_day.id}&mode=builder#builder", status_code=303)


@router.get("/quick", response_class=HTMLResponse)
def create_quick_session_page(
    request: Request,
    training_day_id: int | None = Query(default=None),
    training_plan_id: int | None = Query(default=None),
    day_date: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    session_group_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    training_day = get_training_day(db, training_day_id) if training_day_id is not None else None
    if training_day_id is not None and training_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dia no encontrado")

    training_plan = training_day.training_plan if training_day else None
    selected_day_date: date | None = training_day.day_date if training_day else None

    if training_day is None:
        if training_plan_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falta training_plan_id")
        training_plan = get_training_plan(db, training_plan_id)
        if training_plan is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado")
        if day_date:
            try:
                selected_day_date = date.fromisoformat(day_date)
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fecha invalida") from exc
            existing_day = get_training_day_by_plan_and_date(db, training_plan.id, selected_day_date)
            if existing_day is not None:
                training_day = existing_day

    requested_mode = (mode or "simple").strip().lower()
    initial_mode = requested_mode if requested_mode in {"simple", "text", "builder"} else "simple"
    initial_session_group_id: int | None = None
    available_groups = training_day.session_groups if training_day else []
    if session_group_id is not None and any(group.id == session_group_id for group in available_groups):
        initial_session_group_id = session_group_id

    return templates.TemplateResponse(
        request=request,
        name="planned_sessions/quick.html",
        context={
            "training_day": training_day,
            "training_plan": training_plan,
            "selected_day_date": selected_day_date.isoformat() if selected_day_date else "",
            "session_groups": available_groups,
            "error": request.query_params.get("error"),
            "initial_mode": initial_mode,
            "initial_session_group_id": initial_session_group_id,
        },
    )


@router.get("/{planned_session_id}", response_model=PlannedSessionRead)
def read_planned_session(planned_session_id: int, request: Request, db: Session = Depends(get_db)):
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="planned_sessions/detail.html",
            context={
                "planned_session": planned_session,
                "training_day": planned_session.training_day,
                "latest_report": get_latest_session_report(db, planned_session.id),
                "ui_status": request.query_params.get("ui_status"),
                "match_status": request.query_params.get("match_status"),
                "analysis_status": request.query_params.get("analysis_status"),
            },
        )
    return planned_session


@router.post("/quick")
def create_quick_session_endpoint(
    mode: str = Form(default="simple"),
    training_day_id: str | None = Form(default=None),
    training_plan_id: str | None = Form(default=None),
    planned_day_date: str | None = Form(default=None),
    simple_sport_type: str | None = Form(default=None),
    simple_name: str | None = Form(default=None),
    simple_expected_duration_min: str | None = Form(default=None),
    simple_expected_distance_km: str | None = Form(default=None),
    simple_target_hr_zone: str | None = Form(default=None),
    simple_target_power_zone: str | None = Form(default=None),
    simple_target_notes: str | None = Form(default=None),
    simple_group_mode: str | None = Form(default="existing"),
    simple_session_group_id: str | None = Form(default=None),
    simple_new_group_name: str | None = Form(default=None),
    simple_new_group_type: str | None = Form(default=None),
    simple_new_group_notes: str | None = Form(default=None),
    raw_text: str | None = Form(default=None),
    builder_raw_text: str | None = Form(default=None),
    text_sport_type_override: str | None = Form(default=None),
    text_group_mode: str | None = Form(default="existing"),
    text_session_group_id: str | None = Form(default=None),
    text_new_group_name: str | None = Form(default=None),
    text_new_group_type: str | None = Form(default=None),
    text_new_group_notes: str | None = Form(default=None),
    builder_sport_type_override: str | None = Form(default=None),
    advanced_name: str | None = Form(default=None),
    advanced_is_key_session: bool = Form(default=False),
    advanced_expected_duration_hhmm: str | None = Form(default=None),
    advanced_expected_distance_value: str | None = Form(default=None),
    advanced_expected_distance_unit: str | None = Form(default="km"),
    advanced_target_hr_zone: str | None = Form(default=None),
    advanced_target_power_zone: str | None = Form(default=None),
    advanced_target_notes: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    normalized_mode = (mode or "simple").strip().lower()
    try:
        effective_training_day_id = _resolve_or_create_training_day_id(
            db,
            training_day_id=training_day_id,
            training_plan_id=training_plan_id,
            planned_day_date=planned_day_date,
        )
        if normalized_mode == "simple":
            session_group_id = _resolve_session_group_id(
                db,
                training_day_id=effective_training_day_id,
                group_mode=simple_group_mode,
                session_group_id=simple_session_group_id,
                new_group_name=simple_new_group_name,
                new_group_type=simple_new_group_type,
                new_group_notes=simple_new_group_notes,
            )
        elif normalized_mode == "text":
            session_group_id = _resolve_session_group_id(
                db,
                training_day_id=effective_training_day_id,
                group_mode=text_group_mode,
                session_group_id=text_session_group_id,
                new_group_name=text_new_group_name,
                new_group_type=text_new_group_type,
                new_group_notes=text_new_group_notes,
            )
        else:
            session_group_id = None
        advanced_data = SessionAdvancedData(
            name=(advanced_name or "").strip() or None,
            session_group_id=session_group_id,
            is_key_session=advanced_is_key_session,
            expected_duration_min=_parse_duration_hhmm(advanced_expected_duration_hhmm),
            expected_distance_km=_distance_to_km(advanced_expected_distance_value, advanced_expected_distance_unit),
            target_hr_zone=advanced_target_hr_zone or None,
            target_power_zone=advanced_target_power_zone or None,
            target_notes=advanced_target_notes or None,
        )

        mode_sport = {
            "simple": simple_sport_type or None,
            "text": text_sport_type_override or None,
            "builder": builder_sport_type_override or None,
        }.get(normalized_mode)
        mode_variant = {
            "simple": None,
            "text": None,
            "builder": None,
        }.get(normalized_mode)

        result = create_session_from_quick_mode(
            db,
            training_day_id=effective_training_day_id,
            mode=normalized_mode,
            sport_type=mode_sport,
            discipline_variant=mode_variant,
            name=(simple_name or "").strip() or None,
            description_text=None,
            expected_duration_min=_parse_duration_hhmm(simple_expected_duration_min),
            expected_distance_km=_parse_float_field(simple_expected_distance_km, "La distancia simple debe ser un numero."),
            target_hr_zone=simple_target_hr_zone or None,
            target_power_zone=simple_target_power_zone or None,
            target_notes=simple_target_notes or None,
            raw_text=(builder_raw_text if normalized_mode == "builder" else raw_text) or None,
            is_key_session=advanced_is_key_session,
            advanced_data=advanced_data,
        )
        return RedirectResponse(url=f"/planned_sessions/{result.planned_session.id}", status_code=303)
    except ValueError as exc:
        redirect_target = _quick_session_redirect_target(
            training_day_id=training_day_id,
            training_plan_id=training_plan_id,
            planned_day_date=planned_day_date,
            mode=normalized_mode,
            error=str(exc),
        )
        return RedirectResponse(
            url=redirect_target,
            status_code=303,
        )


@router.post("/parse")
def create_session_from_text_endpoint(
    training_day_id: int = Form(...),
    raw_text: str = Form(...),
    sport_type_override: str | None = Form(default=None),
    discipline_variant_override: str | None = Form(default=None),
    is_key_session: bool = Form(default=False),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        result = create_session_from_natural_language(
            db,
            training_day_id=training_day_id,
            raw_text=raw_text,
            sport_type_override=sport_type_override or None,
            discipline_variant_override=discipline_variant_override or None,
            is_key_session=is_key_session,
        )
        status_message = (
            f"Sesion creada desde texto. Pasos generados: {result.created_steps}. "
            f"Nivel de interpretacion: {result.parse_mode}."
        )
        return RedirectResponse(
            url=f"/planned_sessions/{result.planned_session.id}?ui_status={quote(status_message)}",
            status_code=303,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/planned_sessions/quick?training_day_id={training_day_id}&mode=text&error={quote(str(exc))}#text",
            status_code=303,
        )


@router.get("/{planned_session_id}/edit", response_class=HTMLResponse)
def edit_planned_session_page(planned_session_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")

    return templates.TemplateResponse(
        request=request,
        name="planned_sessions/edit.html",
        context={
            "planned_session": planned_session,
            "training_day": planned_session.training_day,
            "session_groups": planned_session.training_day.session_groups,
        },
    )


@router.post("", response_model=PlannedSessionRead, status_code=status.HTTP_201_CREATED)
def create_planned_session_endpoint(
    planned_session_in: PlannedSessionCreate,
    db: Session = Depends(get_db),
) -> PlannedSessionRead:
    try:
        return create_planned_session(db, planned_session_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{planned_session_id}", response_model=PlannedSessionRead)
def update_planned_session_endpoint(
    planned_session_id: int,
    planned_session_in: PlannedSessionUpdate,
    db: Session = Depends(get_db),
) -> PlannedSessionRead:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    try:
        return update_planned_session(db, planned_session, planned_session_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{planned_session_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_planned_session_endpoint(planned_session_id: int, db: Session = Depends(get_db)) -> Response:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned session not found")
    delete_planned_session(db, planned_session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _parse_duration_hhmm(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    lower_value = normalized.lower().replace(" ", "")

    hhmm_match = lower_value.split(":")
    if len(hhmm_match) == 2:
        try:
            hours = int(hhmm_match[0])
            minutes = int(hhmm_match[1])
        except ValueError as exc:
            raise ValueError("La duracion avanzada no tiene un formato valido.") from exc
        if hours < 0 or minutes < 0 or minutes > 59:
            raise ValueError("La duracion avanzada no tiene un formato valido.")
        return hours * 60 + minutes

    compact_hours_minutes = re.fullmatch(r"(\d+)h(\d{1,2})", lower_value)
    if compact_hours_minutes:
        hours = int(compact_hours_minutes.group(1))
        minutes = int(compact_hours_minutes.group(2))
        if minutes > 59:
            raise ValueError("La duracion avanzada no tiene un formato valido.")
        return hours * 60 + minutes

    hours_only = re.fullmatch(r"(\d+)h(?:s)?", lower_value)
    if hours_only:
        return int(hours_only.group(1)) * 60

    minutes_text = re.fullmatch(r"(\d+)(?:min|m)", lower_value)
    if minutes_text:
        return int(minutes_text.group(1))

    plain_number = re.fullmatch(r"\d+", lower_value)
    if plain_number:
        total_minutes = int(lower_value)
        return total_minutes

    raise ValueError("La duracion avanzada no tiene un formato valido.")


def _parse_planned_start_time(value: str | None) -> time | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        hour_str, minute_str = normalized.split(":")
        return time(hour=int(hour_str), minute=int(minute_str))
    except (TypeError, ValueError) as exc:
        raise ValueError("La hora prevista no tiene un formato valido.") from exc


def _distance_to_km(value: str | float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            numeric_value = float(normalized)
        except ValueError as exc:
            raise ValueError("La distancia esperada debe ser un numero.") from exc
    else:
        numeric_value = value
    return numeric_value / 1000 if unit == "m" else numeric_value


def _parse_int_field(value: str | None, message: str) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(message) from exc


def _parse_float_field(value: str | None, message: str) -> float | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError as exc:
        raise ValueError(message) from exc


def _resolve_session_group_id(
    db: Session,
    *,
    training_day_id: int,
    group_mode: str | None,
    session_group_id: str | None,
    new_group_name: str | None,
    new_group_type: str | None,
    new_group_notes: str | None,
) -> int | None:
    normalized_mode = (group_mode or "existing").strip().lower()
    if normalized_mode == "new":
        group = create_inline_group(
            db,
            training_day_id=training_day_id,
            name=new_group_name or "",
            group_type=new_group_type or None,
            notes=new_group_notes or None,
        )
        return group.id
    return _parse_int_field(session_group_id, "El grupo seleccionado no es valido.")


def _resolve_or_create_training_day_id(
    db: Session,
    *,
    training_day_id: str | None,
    training_plan_id: str | None,
    planned_day_date: str | None,
) -> int:
    resolved_training_day_id = _parse_int_field(training_day_id, "El dia seleccionado no es valido.")
    if resolved_training_day_id is not None:
        training_day = get_training_day(db, resolved_training_day_id)
        if training_day is None:
            raise ValueError("El dia seleccionado no existe.")
        return training_day.id

    resolved_training_plan_id = _parse_int_field(training_plan_id, "El plan seleccionado no es valido.")
    if resolved_training_plan_id is None:
        raise ValueError("Falta el plan para crear la sesion.")
    if not planned_day_date or not planned_day_date.strip():
        raise ValueError("Elegi una fecha para crear la sesion.")
    try:
        parsed_day_date = date.fromisoformat(planned_day_date.strip())
    except ValueError as exc:
        raise ValueError("La fecha elegida no es valida.") from exc

    existing_day = get_training_day_by_plan_and_date(db, resolved_training_plan_id, parsed_day_date)
    if existing_day is not None:
        return existing_day.id

    training_day = create_training_day(
        db,
        TrainingDayCreate(
            training_plan_id=resolved_training_plan_id,
            day_date=parsed_day_date,
            day_notes=None,
            day_type=None,
        ),
    )
    return training_day.id


def _quick_session_redirect_target(
    *,
    training_day_id: str | None,
    training_plan_id: str | None,
    planned_day_date: str | None,
    mode: str,
    error: str,
) -> str:
    query_parts: list[str] = [f"mode={quote(mode)}", f"error={quote(error)}"]
    normalized_training_day_id = (training_day_id or "").strip()
    normalized_training_plan_id = (training_plan_id or "").strip()
    normalized_day_date = (planned_day_date or "").strip()

    if normalized_training_day_id:
        query_parts.append(f"training_day_id={quote(normalized_training_day_id)}")
    if normalized_training_plan_id:
        query_parts.append(f"training_plan_id={quote(normalized_training_plan_id)}")
    if normalized_day_date:
        query_parts.append(f"day_date={quote(normalized_day_date)}")
    return f"/planned_sessions/quick?{'&'.join(query_parts)}#{quote(mode)}"
