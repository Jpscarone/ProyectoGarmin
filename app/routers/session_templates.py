from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.planned_session_service import get_planned_session
from app.services.session_template_service import (
    SessionTemplateInput,
    SessionTemplateStepInput,
    build_template_input_from_session,
    create_session_template,
    create_template_from_planned_session,
    delete_session_template,
    get_session_template,
    instantiate_template_for_day,
    list_session_templates,
    update_session_template,
)
from app.schemas.training_day import TrainingDayCreate
from app.services.training_day_service import create_training_day, get_training_day, get_training_day_by_plan_and_date
from app.services.training_plan_service import get_training_plan
from app.web.templates import build_templates


router = APIRouter(prefix="/session_templates", tags=["session_templates"])
templates = build_templates(Path(__file__).resolve().parent.parent)


@router.get("", response_class=HTMLResponse)
def list_session_templates_page(
    request: Request,
    sport_type: str | None = Query(default=None),
    session_type: str | None = Query(default=None),
    training_day_id: int | None = Query(default=None),
    training_plan_id: int | None = Query(default=None),
    planned_day_date: str | None = Query(default=None),
    return_to: str | None = Query(default=None),
    month: str | None = Query(default=None),
    status_message: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    training_day = get_training_day(db, training_day_id) if training_day_id is not None else None
    training_plan = training_day.training_plan if training_day is not None else (get_training_plan(db, training_plan_id) if training_plan_id is not None else None)
    return templates.TemplateResponse(
        request=request,
        name="session_templates/list.html",
        context={
            "templates_list": list_session_templates(db, sport_type=sport_type or None, session_type=session_type or None),
            "selected_sport_type": sport_type or "",
            "selected_session_type": session_type or "",
            "training_day": training_day,
            "training_plan": training_plan,
            "planned_day_date": planned_day_date or "",
            "return_to": (return_to or "").strip().lower(),
            "calendar_month": month or "",
            "status_message": status_message,
        },
    )


@router.get("/create", response_class=HTMLResponse)
def create_session_template_page(
    request: Request,
    planned_session_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    planned_session = get_planned_session(db, planned_session_id) if planned_session_id is not None else None
    if planned_session_id is not None and planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesion no encontrada")

    template_input = build_template_input_from_session(planned_session) if planned_session else SessionTemplateInput(title="")
    return templates.TemplateResponse(
        request=request,
        name="session_templates/create.html",
        context={
            "template_input": template_input,
            "template_row_steps": _template_row_steps(template_input),
            "source_session": planned_session,
            "error": request.query_params.get("error"),
        },
    )


@router.post("/create")
async def create_session_template_endpoint(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    form = await request.form()
    try:
        template_input = _template_input_from_form(form)
        created_template = create_session_template(db, template_input)
        return RedirectResponse(url=f"/session_templates/{created_template.id}", status_code=303)
    except ValueError as exc:
        source_session_id = (form.get("source_session_id") or "").strip()
        redirect_target = "/session_templates/create"
        if source_session_id:
            redirect_target += f"?planned_session_id={quote(source_session_id)}"
        redirect_target += f"&error={quote(str(exc))}"
        return RedirectResponse(url=redirect_target, status_code=303)


@router.get("/from-session/{planned_session_id}", response_class=HTMLResponse)
def create_template_from_session_page(
    planned_session_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesion no encontrada")

    template_input = build_template_input_from_session(planned_session)
    return templates.TemplateResponse(
        request=request,
        name="session_templates/create.html",
        context={
            "template_input": template_input,
            "template_row_steps": _template_row_steps(template_input),
            "source_session": planned_session,
            "error": request.query_params.get("error"),
        },
    )


@router.post("/from-session/{planned_session_id}")
def create_template_from_session_endpoint(
    planned_session_id: int,
    title: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        template = create_template_from_planned_session(db, planned_session_id=planned_session_id, title=title)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/session_templates/from-session/{planned_session_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(url=f"/session_templates/{template.id}", status_code=303)


@router.get("/{session_template_id}", response_class=HTMLResponse)
def read_session_template_page(
    session_template_id: int,
    request: Request,
    training_day_id: int | None = Query(default=None),
    training_plan_id: int | None = Query(default=None),
    planned_day_date: str | None = Query(default=None),
    return_to: str | None = Query(default=None),
    month: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    session_template = get_session_template(db, session_template_id)
    if session_template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plantilla no encontrada")
    training_day = get_training_day(db, training_day_id) if training_day_id is not None else None
    training_plan = training_day.training_plan if training_day is not None else (get_training_plan(db, training_plan_id) if training_plan_id is not None else None)
    return templates.TemplateResponse(
        request=request,
        name="session_templates/detail.html",
        context={
            "session_template": session_template,
            "training_day": training_day,
            "training_plan": training_plan,
            "planned_day_date": planned_day_date or "",
            "return_to": (return_to or "").strip().lower(),
            "calendar_month": month or "",
            "status_message": request.query_params.get("status_message"),
        },
    )


@router.get("/{session_template_id}/edit", response_class=HTMLResponse)
def edit_session_template_page(
    session_template_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    session_template = get_session_template(db, session_template_id)
    if session_template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plantilla no encontrada")
    template_input = SessionTemplateInput(
        title=session_template.title,
        sport_type=session_template.sport_type,
        discipline_variant=session_template.discipline_variant,
        session_type=session_template.session_type,
        description_text=session_template.description_text,
        expected_duration_min=session_template.expected_duration_min,
        expected_distance_km=session_template.expected_distance_km,
        expected_elevation_gain_m=session_template.expected_elevation_gain_m,
        target_type=session_template.target_type,
        target_hr_zone=session_template.target_hr_zone,
        target_pace_zone=session_template.target_pace_zone,
        target_power_zone=session_template.target_power_zone,
        target_rpe_zone=session_template.target_rpe_zone,
        target_notes=session_template.target_notes,
        is_active=session_template.is_active,
        steps=[
            SessionTemplateStepInput(
                step_order=step.step_order,
                step_type=step.step_type,
                repeat_count=step.repeat_count,
                duration_sec=step.duration_sec,
                distance_m=step.distance_m,
                target_type=step.target_type,
                target_hr_zone=step.target_hr_zone,
                target_hr_min=step.target_hr_min,
                target_hr_max=step.target_hr_max,
                target_power_zone=step.target_power_zone,
                target_power_min=step.target_power_min,
                target_power_max=step.target_power_max,
                target_pace_zone=step.target_pace_zone,
                target_pace_min_sec_km=step.target_pace_min_sec_km,
                target_pace_max_sec_km=step.target_pace_max_sec_km,
                target_rpe_zone=step.target_rpe_zone,
                target_cadence_min=step.target_cadence_min,
                target_cadence_max=step.target_cadence_max,
                target_notes=step.target_notes,
            )
            for step in session_template.steps
        ],
    )
    return templates.TemplateResponse(
        request=request,
        name="session_templates/edit.html",
        context={
            "session_template": session_template,
            "template_input": template_input,
            "template_row_steps": _template_row_steps(template_input),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/{session_template_id}/edit")
async def update_session_template_endpoint(
    session_template_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    session_template = get_session_template(db, session_template_id)
    if session_template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plantilla no encontrada")
    form = await request.form()
    try:
        template_input = _template_input_from_form(form)
        update_session_template(db, session_template, template_input)
        return RedirectResponse(url=f"/session_templates/{session_template.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/session_templates/{session_template_id}/edit?error={quote(str(exc))}",
            status_code=303,
        )


@router.post("/{session_template_id}/delete")
def delete_session_template_endpoint(
    session_template_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    session_template = get_session_template(db, session_template_id)
    if session_template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plantilla no encontrada")
    delete_session_template(db, session_template)
    return RedirectResponse(url="/session_templates", status_code=303)


@router.post("/{session_template_id}/use")
def use_session_template_endpoint(
    session_template_id: int,
    training_day_id: int | None = Form(default=None),
    training_plan_id: int | None = Form(default=None),
    planned_day_date: str | None = Form(default=None),
    return_to: str | None = Form(default=None),
    month: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        effective_training_day_id = _resolve_or_create_template_training_day_id(
            db,
            training_day_id=training_day_id,
            training_plan_id=training_plan_id,
            planned_day_date=planned_day_date,
        )
        planned_session = instantiate_template_for_day(db, session_template_id=session_template_id, training_day_id=effective_training_day_id)
    except ValueError as exc:
        return RedirectResponse(
            url=(
                f"/session_templates?training_day_id={training_day_id or ''}"
                f"&training_plan_id={training_plan_id or ''}"
                f"&planned_day_date={quote(planned_day_date or '')}"
                f"&return_to={quote((return_to or '').strip().lower())}"
                f"&month={quote(month or '')}&status_message={quote(str(exc))}"
            ),
            status_code=303,
        )

    training_day = planned_session.training_day
    normalized_return_to = (return_to or "").strip().lower()
    if normalized_return_to == "calendar":
        month_value = month or training_day.day_date.strftime("%Y-%m")
        return RedirectResponse(
            url=(
                f"/training_plans/{training_day.training_plan.id}/calendar"
                f"?month={month_value}&selected_date={training_day.day_date.isoformat()}"
                f"&status_message={quote('Plantilla copiada al dia.')}"
            ),
            status_code=303,
        )
    if normalized_return_to == "plan":
        return RedirectResponse(
            url=f"/training_plans/{training_day.training_plan.id}#training-day-{training_day.id}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/training_days/{training_day.id}?return_to=plan&ui_status={quote('Plantilla copiada al dia.')}",
        status_code=303,
    )


def _resolve_or_create_template_training_day_id(
    db: Session,
    *,
    training_day_id: int | None,
    training_plan_id: int | None,
    planned_day_date: str | None,
) -> int:
    if training_day_id is not None:
        training_day = get_training_day(db, training_day_id)
        if training_day is None:
            raise ValueError("El dia seleccionado no existe.")
        return training_day.id

    if training_plan_id is None:
        raise ValueError("Falta el plan para copiar la plantilla.")
    if not planned_day_date or not planned_day_date.strip():
        raise ValueError("Elegi una fecha para copiar la plantilla.")
    try:
        parsed_day_date = date.fromisoformat(planned_day_date.strip())
    except ValueError as exc:
        raise ValueError("La fecha elegida no es valida.") from exc

    existing_day = get_training_day_by_plan_and_date(db, training_plan_id, parsed_day_date)
    if existing_day is not None:
        return existing_day.id

    training_day = create_training_day(
        db,
        TrainingDayCreate(
            training_plan_id=training_plan_id,
            day_date=parsed_day_date,
            day_notes=None,
            day_type=None,
        ),
    )
    return training_day.id


def _template_row_steps(template_input: SessionTemplateInput) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for step in template_input.steps or []:
        rows.append(
            {
                "step_order": step.step_order,
                "step_type": step.step_type,
                "repeat_count": step.repeat_count,
                "duration_text": _seconds_to_duration_text(step.duration_sec),
                "distance_m": step.distance_m,
                "target_type": step.target_type,
                "target_hr_zone": step.target_hr_zone,
                "target_hr_min": step.target_hr_min,
                "target_hr_max": step.target_hr_max,
                "target_power_zone": step.target_power_zone,
                "target_power_min": step.target_power_min,
                "target_power_max": step.target_power_max,
                "target_pace_zone": step.target_pace_zone,
                "target_pace_min_sec_km": step.target_pace_min_sec_km,
                "target_pace_max_sec_km": step.target_pace_max_sec_km,
                "target_rpe_zone": step.target_rpe_zone,
                "target_cadence_min": step.target_cadence_min,
                "target_cadence_max": step.target_cadence_max,
                "target_notes": step.target_notes,
            }
        )
    if rows:
        return rows
    return [
        {
            "step_order": 1,
            "step_type": "steady",
            "repeat_count": None,
            "duration_text": "",
            "distance_m": None,
            "target_type": None,
            "target_hr_zone": None,
            "target_hr_min": None,
            "target_hr_max": None,
            "target_power_zone": None,
            "target_power_min": None,
            "target_power_max": None,
            "target_pace_zone": None,
            "target_pace_min_sec_km": None,
            "target_pace_max_sec_km": None,
            "target_rpe_zone": None,
            "target_cadence_min": None,
            "target_cadence_max": None,
            "target_notes": "",
        }
    ]


def _template_input_from_form(form) -> SessionTemplateInput:
    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError("La plantilla necesita un titulo.")

    step_orders = form.getlist("step_order[]")
    step_types = form.getlist("step_type[]")
    repeat_counts = form.getlist("repeat_count[]")
    duration_texts = form.getlist("duration_text[]")
    distance_values = form.getlist("distance_m[]")
    target_types = form.getlist("step_target_type[]")
    target_hr_zones = form.getlist("step_target_hr_zone[]")
    target_hr_mins = form.getlist("target_hr_min[]")
    target_hr_maxs = form.getlist("target_hr_max[]")
    target_power_zones = form.getlist("step_target_power_zone[]")
    target_power_mins = form.getlist("target_power_min[]")
    target_power_maxs = form.getlist("target_power_max[]")
    target_pace_zones = form.getlist("step_target_pace_zone[]")
    target_pace_mins = form.getlist("target_pace_min_sec_km[]")
    target_pace_maxs = form.getlist("target_pace_max_sec_km[]")
    target_rpe_zones = form.getlist("step_target_rpe_zone[]")
    target_cadence_mins = form.getlist("target_cadence_min[]")
    target_cadence_maxs = form.getlist("target_cadence_max[]")
    target_notes_list = form.getlist("step_target_notes[]")

    steps: list[SessionTemplateStepInput] = []
    total_rows = max(len(step_orders), len(step_types), len(duration_texts), len(distance_values), len(target_notes_list))
    for index in range(total_rows):
        step_order = _parse_int(step_orders[index] if index < len(step_orders) else "", default=index + 1)
        step_type = (step_types[index] if index < len(step_types) else "").strip() or "steady"
        duration_text = duration_texts[index] if index < len(duration_texts) else ""
        distance_value = distance_values[index] if index < len(distance_values) else ""
        target_note = target_notes_list[index] if index < len(target_notes_list) else ""

        step_has_content = any(
            (
                duration_text and duration_text.strip(),
                distance_value and str(distance_value).strip(),
                target_note and target_note.strip(),
                step_type and step_type != "steady",
                (target_types[index] if index < len(target_types) else "").strip(),
                (target_hr_zones[index] if index < len(target_hr_zones) else "").strip(),
                (repeat_counts[index] if index < len(repeat_counts) else "").strip(),
                (target_hr_mins[index] if index < len(target_hr_mins) else "").strip(),
                (target_hr_maxs[index] if index < len(target_hr_maxs) else "").strip(),
                (target_power_zones[index] if index < len(target_power_zones) else "").strip(),
                (target_power_mins[index] if index < len(target_power_mins) else "").strip(),
                (target_power_maxs[index] if index < len(target_power_maxs) else "").strip(),
                (target_pace_zones[index] if index < len(target_pace_zones) else "").strip(),
                (target_pace_mins[index] if index < len(target_pace_mins) else "").strip(),
                (target_pace_maxs[index] if index < len(target_pace_maxs) else "").strip(),
                (target_rpe_zones[index] if index < len(target_rpe_zones) else "").strip(),
                (target_cadence_mins[index] if index < len(target_cadence_mins) else "").strip(),
                (target_cadence_maxs[index] if index < len(target_cadence_maxs) else "").strip(),
            )
        )
        if not step_has_content:
            continue

        steps.append(
            SessionTemplateStepInput(
                step_order=step_order,
                step_type=step_type,
                repeat_count=_parse_optional_int(repeat_counts[index] if index < len(repeat_counts) else ""),
                duration_sec=_parse_duration_to_seconds(duration_text),
                distance_m=_parse_optional_int(distance_value),
                target_type=(target_types[index] if index < len(target_types) else "").strip() or None,
                target_hr_zone=(target_hr_zones[index] if index < len(target_hr_zones) else "").strip() or None,
                target_hr_min=_parse_optional_int(target_hr_mins[index] if index < len(target_hr_mins) else ""),
                target_hr_max=_parse_optional_int(target_hr_maxs[index] if index < len(target_hr_maxs) else ""),
                target_power_zone=(target_power_zones[index] if index < len(target_power_zones) else "").strip() or None,
                target_power_min=_parse_optional_int(target_power_mins[index] if index < len(target_power_mins) else ""),
                target_power_max=_parse_optional_int(target_power_maxs[index] if index < len(target_power_maxs) else ""),
                target_pace_zone=(target_pace_zones[index] if index < len(target_pace_zones) else "").strip() or None,
                target_pace_min_sec_km=_parse_optional_int(target_pace_mins[index] if index < len(target_pace_mins) else ""),
                target_pace_max_sec_km=_parse_optional_int(target_pace_maxs[index] if index < len(target_pace_maxs) else ""),
                target_rpe_zone=(target_rpe_zones[index] if index < len(target_rpe_zones) else "").strip() or None,
                target_cadence_min=_parse_optional_int(target_cadence_mins[index] if index < len(target_cadence_mins) else ""),
                target_cadence_max=_parse_optional_int(target_cadence_maxs[index] if index < len(target_cadence_maxs) else ""),
                target_notes=target_note.strip() or None,
            )
        )

    return SessionTemplateInput(
        title=title,
        sport_type=(form.get("sport_type") or "").strip() or None,
        discipline_variant=(form.get("discipline_variant") or "").strip() or None,
        session_type=(form.get("session_type") or "").strip() or None,
        description_text=(form.get("description_text") or "").strip() or None,
        expected_duration_min=_parse_duration_to_minutes(form.get("expected_duration_min") or ""),
        expected_distance_km=_parse_optional_float(form.get("expected_distance_km") or ""),
        expected_elevation_gain_m=_parse_optional_float(form.get("expected_elevation_gain_m") or ""),
        target_type=(form.get("target_type") or "").strip() or None,
        target_hr_zone=(form.get("target_hr_zone") or "").strip() or None,
        target_pace_zone=(form.get("target_pace_zone") or "").strip() or None,
        target_power_zone=(form.get("target_power_zone") or "").strip() or None,
        target_rpe_zone=(form.get("target_rpe_zone") or "").strip() or None,
        target_notes=(form.get("target_notes") or "").strip() or None,
        is_active=(form.get("is_active") or "").strip() == "on",
        steps=sorted(steps, key=lambda step: (step.step_order, step.step_type)),
    )


def _parse_int(value: str | None, *, default: int) -> int:
    normalized = (value or "").strip()
    if not normalized:
        return default
    return int(normalized)


def _parse_optional_int(value: str | None) -> int | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    return int(float(normalized))


def _parse_optional_float(value: str | None) -> float | None:
    normalized = (value or "").strip().replace(",", ".")
    if not normalized:
        return None
    return float(normalized)


def _parse_duration_to_minutes(value: str | None) -> int | None:
    normalized = (value or "").strip().lower().replace(" ", "")
    if not normalized:
        return None
    if ":" in normalized:
        parts = normalized.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    if normalized.endswith("min"):
        return int(normalized[:-3])
    if normalized.endswith("h"):
        return int(normalized[:-1]) * 60
    if "h" in normalized:
        hours_text, minutes_text = normalized.split("h", 1)
        return int(hours_text) * 60 + int(minutes_text or "0")
    return int(normalized)


def _parse_duration_to_seconds(value: str | None) -> int | None:
    normalized = (value or "").strip().lower().replace(" ", "")
    if not normalized:
        return None
    if ":" in normalized:
        parts = normalized.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    if normalized.endswith("seg"):
        return int(normalized[:-3])
    if normalized.endswith("s"):
        return int(normalized[:-1])
    if normalized.endswith("min"):
        return int(normalized[:-3]) * 60
    if normalized.endswith("m"):
        return int(normalized[:-1]) * 60
    if normalized.endswith("h"):
        return int(normalized[:-1]) * 3600
    if "h" in normalized:
        hours_text, minutes_text = normalized.split("h", 1)
        return int(hours_text) * 3600 + int(minutes_text or "0") * 60
    return int(normalized) * 60


def _seconds_to_duration_text(seconds: int | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    if seconds % 60 == 0 and seconds < 3600:
        return f"{seconds // 60}min"
    if seconds < 3600:
        return f"{seconds // 60}:{seconds % 60:02d}"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}:{minutes:02d}"
