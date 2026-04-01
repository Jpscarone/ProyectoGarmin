from __future__ import annotations

import json
import re
from datetime import date, time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.planned_session import PlannedSessionCreate, PlannedSessionRead, PlannedSessionUpdate
from app.schemas.planned_session_step import PlannedSessionStepCreate
from app.services.analysis.report_service import get_latest_session_report
from app.services.intensity_target_service import normalize_step_target_fields
from app.services.planning.quick_session_service import (
    SessionAdvancedData,
    create_session_from_quick_mode,
)
from app.services.planning.parser import parse_session_text
from app.services.planning.presentation import build_session_display_blocks
from app.services.planned_session_service import (
    create_planned_session,
    delete_planned_session,
    get_planned_session,
    get_planned_sessions,
    update_planned_session,
)
from app.services.planned_session_step_service import replace_steps_for_session
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
    planned_session_id: int | None = Query(default=None),
    mode: str | None = Query(default=None),
    session_group_id: int | None = Query(default=None),
    return_to: str | None = Query(default=None),
    month: str | None = Query(default=None),
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    editing_session = get_planned_session(db, planned_session_id) if planned_session_id is not None else None
    if planned_session_id is not None and editing_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesion no encontrada")

    training_day = editing_session.training_day if editing_session else (get_training_day(db, training_day_id) if training_day_id is not None else None)
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

    requested_mode = (mode or _infer_quick_mode_for_planned_session(editing_session)).strip().lower()
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
            "return_to": (return_to or "").strip().lower(),
            "return_month": month or "",
            "return_selected_date": selected_date or (selected_day_date.isoformat() if selected_day_date else ""),
            "editing_session": editing_session,
            "initial_quick_data": _build_initial_quick_data(editing_session, initial_mode) if editing_session else None,
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
    planned_session_id: str | None = Form(default=None),
    training_day_id: str | None = Form(default=None),
    training_plan_id: str | None = Form(default=None),
    planned_day_date: str | None = Form(default=None),
    simple_sport_type: str | None = Form(default=None),
    simple_name: str | None = Form(default=None),
    simple_expected_duration_min: str | None = Form(default=None),
    simple_expected_distance_km: str | None = Form(default=None),
    simple_target_type: str | None = Form(default=None),
    simple_target_hr_zone: str | None = Form(default=None),
    simple_target_pace_zone: str | None = Form(default=None),
    simple_target_power_zone: str | None = Form(default=None),
    simple_target_rpe_zone: str | None = Form(default=None),
    simple_target_notes: str | None = Form(default=None),
    builder_blocks_json: str | None = Form(default=None),
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
    advanced_target_type: str | None = Form(default=None),
    advanced_target_hr_zone: str | None = Form(default=None),
    advanced_target_pace_zone: str | None = Form(default=None),
    advanced_target_power_zone: str | None = Form(default=None),
    advanced_target_rpe_zone: str | None = Form(default=None),
    advanced_target_notes: str | None = Form(default=None),
    return_to: str | None = Form(default=None),
    return_month: str | None = Form(default=None),
    return_selected_date: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    normalized_mode = (mode or "simple").strip().lower()
    try:
        editing_session = None
        resolved_planned_session_id = _parse_int_field(planned_session_id, "La sesion seleccionada no es valida.")
        if resolved_planned_session_id is not None:
            editing_session = get_planned_session(db, resolved_planned_session_id)
            if editing_session is None:
                raise ValueError("La sesion seleccionada no existe.")

        effective_training_day_id = _resolve_or_create_training_day_id(
            db,
            training_day_id=training_day_id or (str(editing_session.training_day_id) if editing_session else None),
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
            target_type=advanced_target_type or None,
            target_hr_zone=advanced_target_hr_zone or None,
            target_pace_zone=advanced_target_pace_zone or None,
            target_power_zone=advanced_target_power_zone or None,
            target_rpe_zone=advanced_target_rpe_zone or None,
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

        raw_session_text = (builder_raw_text if normalized_mode == "builder" else raw_text) or None
        if editing_session is not None:
            result = _update_session_from_quick_mode(
                db,
                planned_session=editing_session,
                training_day_id=effective_training_day_id,
                mode=normalized_mode,
                sport_type=mode_sport,
                discipline_variant=mode_variant,
                name=(simple_name or "").strip() or None,
                expected_duration_min=_parse_duration_hhmm(simple_expected_duration_min),
                expected_distance_km=_parse_float_field(simple_expected_distance_km, "La distancia simple debe ser un numero."),
                target_type=simple_target_type or None,
                target_hr_zone=simple_target_hr_zone or None,
                target_pace_zone=simple_target_pace_zone or None,
                target_power_zone=simple_target_power_zone or None,
                target_rpe_zone=simple_target_rpe_zone or None,
                target_notes=simple_target_notes or None,
                raw_text=raw_session_text,
                builder_blocks_json=builder_blocks_json,
                is_key_session=advanced_is_key_session,
                advanced_data=advanced_data,
            )
        else:
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
                target_type=simple_target_type or None,
                target_hr_zone=simple_target_hr_zone or None,
                target_pace_zone=simple_target_pace_zone or None,
                target_power_zone=simple_target_power_zone or None,
                target_rpe_zone=simple_target_rpe_zone or None,
                target_notes=simple_target_notes or None,
                raw_text=raw_session_text,
                is_key_session=advanced_is_key_session,
                advanced_data=advanced_data,
            )
        created_training_day = get_training_day(db, effective_training_day_id)
        normalized_return_to = (return_to or "").strip().lower()
        if normalized_return_to == "calendar" and created_training_day is not None:
            calendar_month = return_month or created_training_day.day_date.strftime("%Y-%m")
            selected_day = return_selected_date or created_training_day.day_date.isoformat()
            return RedirectResponse(
                url=(
                    f"/training_plans/{created_training_day.training_plan.id}/calendar"
                    f"?month={quote(calendar_month)}&selected_date={quote(selected_day)}&status={quote('Sesion creada')}"
                ),
                status_code=303,
            )
        if normalized_return_to == "plan" and created_training_day is not None:
            return RedirectResponse(
                url=f"/training_plans/{created_training_day.training_plan.id}#training-day-{created_training_day.id}",
                status_code=303,
            )
        if editing_session is not None:
            return RedirectResponse(url=f"/planned_sessions/{result.planned_session.id}", status_code=303)
        return RedirectResponse(url=f"/planned_sessions/{result.planned_session.id}", status_code=303)
    except ValueError as exc:
        redirect_target = _quick_session_redirect_target(
            planned_session_id=planned_session_id,
            training_day_id=training_day_id,
            training_plan_id=training_plan_id,
            planned_day_date=planned_day_date,
            mode=normalized_mode,
            error=str(exc),
            return_to=return_to,
            return_month=return_month,
            return_selected_date=return_selected_date,
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
    mode = _infer_quick_mode_for_planned_session(planned_session)
    return RedirectResponse(url=f"/planned_sessions/quick?planned_session_id={planned_session.id}&mode={quote(mode)}#{quote(mode)}", status_code=303)


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


def _parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


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
    planned_session_id: str | None = None,
    training_day_id: str | None,
    training_plan_id: str | None,
    planned_day_date: str | None,
    mode: str,
    error: str,
    return_to: str | None = None,
    return_month: str | None = None,
    return_selected_date: str | None = None,
) -> str:
    query_parts: list[str] = [f"mode={quote(mode)}", f"error={quote(error)}"]
    normalized_planned_session_id = (planned_session_id or "").strip()
    normalized_training_day_id = (training_day_id or "").strip()
    normalized_training_plan_id = (training_plan_id or "").strip()
    normalized_day_date = (planned_day_date or "").strip()

    if normalized_planned_session_id:
        query_parts.append(f"planned_session_id={quote(normalized_planned_session_id)}")
    if normalized_training_day_id:
        query_parts.append(f"training_day_id={quote(normalized_training_day_id)}")
    if normalized_training_plan_id:
        query_parts.append(f"training_plan_id={quote(normalized_training_plan_id)}")
    if normalized_day_date:
        query_parts.append(f"day_date={quote(normalized_day_date)}")
    normalized_return_to = (return_to or "").strip()
    normalized_return_month = (return_month or "").strip()
    normalized_return_selected_date = (return_selected_date or "").strip()
    if normalized_return_to:
        query_parts.append(f"return_to={quote(normalized_return_to)}")
    if normalized_return_month:
        query_parts.append(f"month={quote(normalized_return_month)}")
    if normalized_return_selected_date:
        query_parts.append(f"selected_date={quote(normalized_return_selected_date)}")
    return f"/planned_sessions/quick?{'&'.join(query_parts)}#{quote(mode)}"


def _infer_quick_mode_for_planned_session(planned_session) -> str:
    if planned_session is None:
        return "simple"
    if planned_session.planned_session_steps:
        return "builder"
    if planned_session.description_text:
        return "text"
    return "simple"


def _build_initial_quick_data(planned_session, initial_mode: str) -> dict:
    display_blocks = build_session_display_blocks(list(planned_session.planned_session_steps or []))
    return {
        "id": planned_session.id,
        "mode": initial_mode,
        "simple": {
            "sportType": planned_session.sport_type or "",
            "name": planned_session.name or "",
            "expectedDuration": _minutes_to_hhmm(planned_session.expected_duration_min),
            "expectedDistance": _float_to_string(planned_session.expected_distance_km),
            "targetType": planned_session.target_type or "",
            "targetHrZone": planned_session.target_hr_zone or "",
            "targetPaceZone": planned_session.target_pace_zone or "",
            "targetPowerZone": planned_session.target_power_zone or "",
            "targetRpeZone": planned_session.target_rpe_zone or "",
            "targetNotes": planned_session.target_notes or "",
            "sessionGroupId": planned_session.session_group_id or "",
        },
        "text": {
            "rawText": planned_session.description_text or "",
            "sportType": planned_session.sport_type or "",
            "sessionGroupId": planned_session.session_group_id or "",
        },
        "advanced": {
            "name": planned_session.name or "",
            "expectedDuration": _minutes_to_hhmm(planned_session.expected_duration_min),
            "expectedDistance": _float_to_string(planned_session.expected_distance_km),
            "targetType": planned_session.target_type or "",
            "targetHrZone": planned_session.target_hr_zone or "",
            "targetPaceZone": planned_session.target_pace_zone or "",
            "targetPowerZone": planned_session.target_power_zone or "",
            "targetRpeZone": planned_session.target_rpe_zone or "",
            "targetNotes": planned_session.target_notes or "",
            "isKeySession": planned_session.is_key_session,
        },
        "builder": {
            "sportType": planned_session.sport_type or "running",
            "rawText": planned_session.description_text or "",
            "blocks": [_display_block_to_builder_data(block, planned_session.target_type) for block in display_blocks],
        },
    }


def _display_block_to_builder_data(block, fallback_target_type: str | None = None) -> dict:
    if block.kind == "repeat":
        return {
            "kind": "repeat",
            "repeatCount": block.repeat_count,
            "steps": [_simple_block_to_builder_data(step, fallback_target_type) for step in block.steps],
        }
    return _simple_block_to_builder_data(block, fallback_target_type)


def _simple_block_to_builder_data(block, fallback_target_type: str | None = None) -> dict:
    value, unit = _measurement_to_builder_fields(block.duration_sec, block.distance_m)
    target_type = block.target_type or _infer_target_type_from_block(block, fallback_target_type)
    target_zone, custom_min, custom_max = _builder_target_fields_from_block(block, target_type)
    return {
        "kind": "simple",
        "value": value,
        "unit": unit,
        "targetType": target_type or "",
        "targetZone": target_zone or "",
        "customMin": custom_min or "",
        "customMax": custom_max or "",
        "stepType": block.step_type or "",
    }


def _measurement_to_builder_fields(duration_sec: int | None, distance_m: int | None) -> tuple[str, str]:
    if duration_sec:
        if duration_sec % 3600 == 0:
            return str(int(duration_sec / 3600)), "h"
        if duration_sec % 60 == 0:
            return str(int(duration_sec / 60)), "min"
        return str(int(duration_sec)), "seg"
    if distance_m:
        if distance_m % 1000 == 0:
            return str(distance_m // 1000), "km"
        return str(int(distance_m)), "m"
    return "", "min"


def _infer_target_type_from_block(block, fallback_target_type: str | None = None) -> str | None:
    if block.target_hr_zone or block.target_hr_min or block.target_hr_max:
        return "hr"
    if block.target_pace_zone or block.target_pace_min_sec_km or block.target_pace_max_sec_km:
        return "pace"
    if block.target_power_zone or block.target_power_min or block.target_power_max:
        return "power"
    if block.target_rpe_zone:
        return "rpe"
    if (block.target_notes or "").strip().upper() in {"Z1", "Z2", "Z3", "Z4", "Z5"}:
        return fallback_target_type
    return fallback_target_type


def _builder_target_fields_from_block(block, target_type: str | None) -> tuple[str | None, str | None, str | None]:
    if target_type == "hr":
        if block.target_hr_zone:
            return block.target_hr_zone, None, None
        if block.target_hr_min is not None or block.target_hr_max is not None:
            return "__custom__", _float_to_string(block.target_hr_min), _float_to_string(block.target_hr_max)
    if target_type == "pace":
        if block.target_pace_zone:
            return block.target_pace_zone, None, None
        if block.target_pace_min_sec_km is not None or block.target_pace_max_sec_km is not None:
            return "__custom__", _seconds_to_pace(block.target_pace_min_sec_km), _seconds_to_pace(block.target_pace_max_sec_km)
    if target_type == "power":
        if block.target_power_zone:
            return block.target_power_zone, None, None
        if block.target_power_min is not None or block.target_power_max is not None:
            return "__custom__", _float_to_string(block.target_power_min), _float_to_string(block.target_power_max)
    if target_type == "rpe" and block.target_rpe_zone:
        return block.target_rpe_zone, None, None
    if (block.target_notes or "").strip().upper() in {"Z1", "Z2", "Z3", "Z4", "Z5"}:
        return (block.target_notes or "").strip().upper(), None, None
    return None, None, None


def _seconds_to_pace(value: int | None) -> str | None:
    if value is None:
        return None
    minutes = value // 60
    seconds = value % 60
    return f"{minutes}:{seconds:02d}"


def _minutes_to_hhmm(value: int | None) -> str:
    if value is None:
        return ""
    hours = value // 60
    minutes = value % 60
    return f"{hours}:{minutes:02d}"


def _float_to_string(value: int | float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _update_session_from_quick_mode(
    db: Session,
    *,
    planned_session,
    training_day_id: int,
    mode: str,
    sport_type: str | None = None,
    discipline_variant: str | None = None,
    name: str | None = None,
    expected_duration_min: int | None = None,
    expected_distance_km: float | None = None,
    target_type: str | None = None,
    target_hr_zone: str | None = None,
    target_pace_zone: str | None = None,
    target_power_zone: str | None = None,
    target_rpe_zone: str | None = None,
    target_notes: str | None = None,
    raw_text: str | None = None,
    builder_blocks_json: str | None = None,
    is_key_session: bool = False,
    advanced_data: SessionAdvancedData | None = None,
):
    advanced = advanced_data or SessionAdvancedData()
    normalized_mode = mode.strip().lower()

    if normalized_mode == "simple":
        parse_source = " ".join(part.strip() for part in ((name or ""), (raw_text or "")) if part and part.strip())
        parsed = parse_session_text(parse_source, fallback_sport_type=sport_type) if parse_source else None
        updated_session = update_planned_session(
            db,
            planned_session,
            PlannedSessionUpdate(
                training_day_id=training_day_id,
                sport_type=sport_type or (parsed.sport_type if parsed else planned_session.sport_type),
                discipline_variant=discipline_variant or (parsed.discipline_variant if parsed else planned_session.discipline_variant),
                name=advanced.name or name or planned_session.name,
                description_text=raw_text or planned_session.description_text,
                session_type=(parsed.session_type if parsed else planned_session.session_type) or advanced.session_type,
                session_group_id=advanced.session_group_id,
                expected_duration_min=expected_duration_min if expected_duration_min is not None else (parsed.expected_duration_min if parsed else advanced.expected_duration_min),
                expected_distance_km=expected_distance_km if expected_distance_km is not None else (parsed.expected_distance_km if parsed else advanced.expected_distance_km),
                expected_elevation_gain_m=advanced.expected_elevation_gain_m,
                target_type=target_type or advanced.target_type,
                target_hr_zone=target_hr_zone or advanced.target_hr_zone,
                target_pace_zone=target_pace_zone or advanced.target_pace_zone,
                target_power_zone=target_power_zone or advanced.target_power_zone,
                target_rpe_zone=target_rpe_zone or advanced.target_rpe_zone,
                target_notes=target_notes or advanced.target_notes,
                is_key_session=advanced.is_key_session if advanced.is_key_session is not None else is_key_session,
            ),
        )
        replace_steps_for_session(db, updated_session, _build_default_steps_for_updated_session(updated_session))
        return type("QuickResult", (), {"planned_session": updated_session})

    if normalized_mode == "text":
        if not raw_text or not raw_text.strip():
            raise ValueError("Escribi la sesion antes de guardar.")
        parsed = parse_session_text(raw_text, fallback_sport_type=sport_type)
        updated_session = update_planned_session(
            db,
            planned_session,
            PlannedSessionUpdate(
                training_day_id=training_day_id,
                sport_type=sport_type or parsed.sport_type or planned_session.sport_type,
                discipline_variant=discipline_variant or parsed.discipline_variant or planned_session.discipline_variant,
                name=advanced.name or parsed.name or planned_session.name,
                description_text=raw_text,
                session_type=parsed.session_type or advanced.session_type or planned_session.session_type,
                session_group_id=advanced.session_group_id,
                expected_duration_min=parsed.expected_duration_min if parsed.expected_duration_min is not None else advanced.expected_duration_min,
                expected_distance_km=parsed.expected_distance_km if parsed.expected_distance_km is not None else advanced.expected_distance_km,
                expected_elevation_gain_m=advanced.expected_elevation_gain_m,
                target_type=advanced.target_type,
                target_hr_zone=parsed.target_hr_zone or advanced.target_hr_zone,
                target_pace_zone=advanced.target_pace_zone,
                target_power_zone=parsed.target_power_zone or advanced.target_power_zone,
                target_rpe_zone=advanced.target_rpe_zone,
                target_notes=parsed.target_notes or advanced.target_notes,
                is_key_session=advanced.is_key_session if advanced.is_key_session is not None else is_key_session,
            ),
        )
        replace_steps_for_session(db, updated_session, _build_parsed_steps_for_updated_session(updated_session, parsed))
        return type("QuickResult", (), {"planned_session": updated_session})

    if normalized_mode == "builder":
        if not raw_text or not raw_text.strip():
            raise ValueError("Arma al menos un bloque antes de guardar.")
        parsed = parse_session_text(raw_text, fallback_sport_type=sport_type)
        updated_session = update_planned_session(
            db,
            planned_session,
            PlannedSessionUpdate(
                training_day_id=training_day_id,
                sport_type=sport_type or parsed.sport_type or planned_session.sport_type,
                discipline_variant=discipline_variant or parsed.discipline_variant or planned_session.discipline_variant,
                name=advanced.name or parsed.name or planned_session.name,
                description_text=raw_text,
                session_type=parsed.session_type or advanced.session_type or planned_session.session_type,
                session_group_id=advanced.session_group_id,
                expected_duration_min=advanced.expected_duration_min if advanced.expected_duration_min is not None else parsed.expected_duration_min,
                expected_distance_km=advanced.expected_distance_km if advanced.expected_distance_km is not None else parsed.expected_distance_km,
                expected_elevation_gain_m=advanced.expected_elevation_gain_m,
                target_type=advanced.target_type or planned_session.target_type,
                target_hr_zone=advanced.target_hr_zone or planned_session.target_hr_zone,
                target_pace_zone=advanced.target_pace_zone or planned_session.target_pace_zone,
                target_power_zone=advanced.target_power_zone or planned_session.target_power_zone,
                target_rpe_zone=advanced.target_rpe_zone or planned_session.target_rpe_zone,
                target_notes=advanced.target_notes,
                is_key_session=advanced.is_key_session if advanced.is_key_session is not None else is_key_session,
            ),
        )
        replace_steps_for_session(db, updated_session, _build_builder_steps_for_updated_session(updated_session, builder_blocks_json))
        return type("QuickResult", (), {"planned_session": updated_session})

    raise ValueError("Modo de edicion no valido.")


def _build_default_steps_for_updated_session(planned_session) -> list[PlannedSessionStepCreate]:
    duration_sec = planned_session.expected_duration_min * 60 if planned_session.expected_duration_min is not None else None
    distance_m = int(round(planned_session.expected_distance_km * 1000)) if planned_session.expected_distance_km is not None else None
    if duration_sec is None and distance_m is None:
        return []
    return [
        PlannedSessionStepCreate(
            **normalize_step_target_fields(
                {
                    "planned_session_id": planned_session.id,
                    "step_order": 1,
                    "step_type": "steady",
                    "repeat_count": None,
                    "duration_sec": duration_sec,
                    "distance_m": distance_m,
                    "target_type": planned_session.target_type,
                    "target_hr_zone": planned_session.target_hr_zone,
                    "target_pace_zone": planned_session.target_pace_zone,
                    "target_power_zone": planned_session.target_power_zone,
                    "target_rpe_zone": planned_session.target_rpe_zone,
                    "target_notes": planned_session.target_notes,
                },
                planned_session.athlete,
            )
        )
    ]


def _build_parsed_steps_for_updated_session(planned_session, parsed) -> list[PlannedSessionStepCreate]:
    if parsed.steps:
        return [
            PlannedSessionStepCreate(
                planned_session_id=planned_session.id,
                step_order=step.step_order,
                step_type=step.step_type,
                repeat_count=step.repeat_count,
                duration_sec=step.duration_sec,
                distance_m=step.distance_m,
                target_notes=step.target_notes,
            )
            for step in parsed.steps
        ]
    return _build_default_steps_for_updated_session(planned_session)


def _build_builder_steps_for_updated_session(planned_session, builder_blocks_json: str | None) -> list[PlannedSessionStepCreate]:
    try:
        blocks = json.loads(builder_blocks_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("La estructura de bloques no es valida.") from exc

    steps: list[PlannedSessionStepCreate] = []
    step_order = 1
    for block in blocks:
        kind = (block.get("kind") or "").strip().lower()
        if kind == "repeat":
            repeat_count = _coerce_positive_int(block.get("repeatCount"))
            nested_steps = block.get("steps") or []
            if not repeat_count or not nested_steps:
                continue
            for index, nested in enumerate(nested_steps, start=1):
                steps.append(
                    _builder_step_create_from_payload(
                        planned_session=planned_session,
                        payload=nested,
                        step_order=step_order,
                        repeat_count=repeat_count,
                        fallback_step_type="work" if index == 1 else "recovery",
                    )
                )
                step_order += 1
        elif kind == "simple":
            steps.append(
                _builder_step_create_from_payload(
                    planned_session=planned_session,
                    payload=block,
                    step_order=step_order,
                    repeat_count=None,
                    fallback_step_type="steady",
                )
            )
            step_order += 1

    return steps or _build_default_steps_for_updated_session(planned_session)


def _builder_step_create_from_payload(*, planned_session, payload: dict, step_order: int, repeat_count: int | None, fallback_step_type: str) -> PlannedSessionStepCreate:
    value = str(payload.get("value") or "").strip()
    unit = str(payload.get("unit") or "").strip().lower()
    target_type = (payload.get("targetType") or "").strip().lower() or None
    target_zone = (payload.get("targetZone") or "").strip() or None
    custom_min = (payload.get("customMin") or "").strip() or None
    custom_max = (payload.get("customMax") or "").strip() or None
    duration_sec, distance_m = _builder_value_to_metrics(value, unit)
    step_type = (payload.get("stepType") or "").strip().lower() or fallback_step_type

    step_data: dict[str, object] = {
        "planned_session_id": planned_session.id,
        "step_order": step_order,
        "step_type": step_type,
        "repeat_count": repeat_count,
        "duration_sec": duration_sec,
        "distance_m": distance_m,
        "target_type": target_type,
        "target_hr_zone": None,
        "target_pace_zone": None,
        "target_power_zone": None,
        "target_rpe_zone": None,
        "target_hr_min": None,
        "target_hr_max": None,
        "target_power_min": None,
        "target_power_max": None,
        "target_pace_min_sec_km": None,
        "target_pace_max_sec_km": None,
    }

    if target_type == "hr":
        if target_zone == "__custom__":
            step_data["target_hr_min"] = _parse_optional_int(custom_min)
            step_data["target_hr_max"] = _parse_optional_int(custom_max)
        else:
            step_data["target_hr_zone"] = target_zone
    elif target_type == "pace":
        if target_zone == "__custom__":
            step_data["target_pace_min_sec_km"] = _parse_pace_to_seconds(custom_min)
            step_data["target_pace_max_sec_km"] = _parse_pace_to_seconds(custom_max)
        else:
            step_data["target_pace_zone"] = target_zone
    elif target_type == "power":
        if target_zone == "__custom__":
            step_data["target_power_min"] = _parse_optional_int(custom_min)
            step_data["target_power_max"] = _parse_optional_int(custom_max)
        else:
            step_data["target_power_zone"] = target_zone
    elif target_type == "rpe":
        step_data["target_rpe_zone"] = target_zone

    target_note = _builder_step_note_from_payload(payload, target_type, target_zone)
    if target_note:
        step_data["target_notes"] = target_note

    return PlannedSessionStepCreate(**normalize_step_target_fields(step_data, planned_session.athlete))


def _builder_value_to_metrics(value: str, unit: str) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    numeric_value = float(value.replace(",", "."))
    if unit == "seg":
        return int(round(numeric_value)), None
    if unit == "min":
        return int(round(numeric_value * 60)), None
    if unit == "h":
        return int(round(numeric_value * 3600)), None
    if unit == "m":
        return None, int(round(numeric_value))
    if unit == "km":
        return None, int(round(numeric_value * 1000))
    return None, None


def _builder_step_note_from_payload(payload: dict, target_type: str | None, target_zone: str | None) -> str | None:
    if target_zone and target_zone not in {"", "__custom__"}:
        return target_zone
    if target_zone == "__custom__":
        custom_min = (payload.get("customMin") or "").strip()
        custom_max = (payload.get("customMax") or "").strip()
        if target_type == "pace":
            return f"ritmo {custom_min}-{custom_max}".strip("-")
        if target_type == "hr":
            return f"FC {custom_min}-{custom_max}".strip("-")
        if target_type == "power":
            return f"potencia {custom_min}-{custom_max}".strip("-")
    return None


def _parse_pace_to_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{1,2})", normalized)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    if seconds > 59:
        return None
    return minutes * 60 + seconds


def _coerce_positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
