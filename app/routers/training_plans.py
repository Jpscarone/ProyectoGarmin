from __future__ import annotations

import calendar
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.training_day import TrainingDayCreate
from app.schemas.training_plan import TrainingPlanCreate, TrainingPlanRead, TrainingPlanUpdate
from app.services.athlete_service import get_athletes
from app.services.planning.presentation import derive_session_metrics, describe_session_structure_short
from app.services.training_day_service import create_training_day
from app.services.training_plan_service import (
    create_training_plan,
    delete_training_plan,
    get_training_plan,
    get_training_plan_detail,
    get_training_plans,
    update_training_plan,
)
from app.web.templates import build_templates


router = APIRouter(prefix="/training_plans", tags=["training_plans"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[TrainingPlanRead])
def list_training_plans(request: Request, db: Session = Depends(get_db)):
    training_plans = get_training_plans(db)
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="training_plans/list.html",
            context={"training_plans": training_plans},
        )
    return training_plans


@router.get("/create", response_class=HTMLResponse)
def create_training_plan_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="training_plans/create.html",
        context={
            "training_plan": None,
            "athletes": get_athletes(db),
        },
    )


@router.get("/{training_plan_id}", response_model=TrainingPlanRead)
def read_training_plan(training_plan_id: int, request: Request, db: Session = Depends(get_db)):
    if _wants_html(request):
        training_plan = get_training_plan_detail(db, training_plan_id)
        if training_plan is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")
        return templates.TemplateResponse(
            request=request,
            name="training_plans/detail.html",
            context={"training_plan": training_plan},
        )

    training_plan = get_training_plan(db, training_plan_id)
    if training_plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")
    return training_plan


@router.get("/{training_plan_id}/calendar", response_class=HTMLResponse)
def read_training_plan_calendar(
    training_plan_id: int,
    request: Request,
    month: str | None = Query(default=None),
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    training_plan = get_training_plan_detail(db, training_plan_id)
    if training_plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")

    visible_month = _resolve_visible_month(training_plan, month)
    selected_day_date = _resolve_selected_date(selected_date, visible_month, training_plan)
    calendar_context = _build_calendar_context(training_plan, visible_month, selected_day_date)

    return templates.TemplateResponse(
        request=request,
        name="training_plans/calendar.html",
        context={
            "training_plan": training_plan,
            "calendar_weeks": calendar_context["weeks"],
            "calendar_month_label": calendar_context["month_label"],
            "visible_month": visible_month.strftime("%Y-%m"),
            "today_iso": date.today().isoformat(),
            "selected_day_date": selected_day_date,
            "selected_day": calendar_context["selected_day"],
            "selected_day_cell": calendar_context["selected_day_cell"],
            "previous_month": calendar_context["previous_month"],
            "next_month": calendar_context["next_month"],
            "status_message": request.query_params.get("status"),
        },
    )


@router.post("/{training_plan_id}/calendar/create-day")
def create_training_day_from_calendar(
    training_plan_id: int,
    day_date: str = Form(...),
    next_action: str = Form(default="calendar"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    training_plan = get_training_plan_detail(db, training_plan_id)
    if training_plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")

    try:
        parsed_day_date = date.fromisoformat(day_date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid day date") from exc

    existing_day = next((day for day in training_plan.training_days if day.day_date == parsed_day_date), None)
    training_day = existing_day

    if training_day is None:
        training_day = create_training_day(
            db,
            training_day_in=TrainingDayCreate(
                training_plan_id=training_plan.id,
                athlete_id=training_plan.athlete_id,
                day_date=parsed_day_date,
                day_notes=None,
                day_type=None,
            ),
        )

    redirect_url = _calendar_next_action_url(training_plan.id, training_day.id, training_day.day_date, next_action)
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/{training_plan_id}/edit", response_class=HTMLResponse)
def edit_training_plan_page(training_plan_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    training_plan = get_training_plan_detail(db, training_plan_id)
    if training_plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")

    return templates.TemplateResponse(
        request=request,
        name="training_plans/edit.html",
        context={
            "training_plan": training_plan,
            "athletes": get_athletes(db),
        },
    )


@router.post("", response_model=TrainingPlanRead, status_code=status.HTTP_201_CREATED)
def create_training_plan_endpoint(training_plan_in: TrainingPlanCreate, db: Session = Depends(get_db)) -> TrainingPlanRead:
    try:
        return create_training_plan(db, training_plan_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{training_plan_id}", response_model=TrainingPlanRead)
def update_training_plan_endpoint(
    training_plan_id: int,
    training_plan_in: TrainingPlanUpdate,
    db: Session = Depends(get_db),
) -> TrainingPlanRead:
    training_plan = get_training_plan(db, training_plan_id)
    if training_plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")
    try:
        return update_training_plan(db, training_plan, training_plan_in)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{training_plan_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_training_plan_endpoint(training_plan_id: int, db: Session = Depends(get_db)) -> Response:
    training_plan = get_training_plan(db, training_plan_id)
    if training_plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")
    delete_training_plan(db, training_plan)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _resolve_visible_month(training_plan, month_param: str | None) -> date:
    if month_param:
        try:
            return datetime.strptime(month_param, "%Y-%m").date().replace(day=1)
        except ValueError:
            pass

    if training_plan.start_date:
        return training_plan.start_date.replace(day=1)

    if training_plan.training_days:
        return min(day.day_date for day in training_plan.training_days).replace(day=1)

    today = date.today()
    return today.replace(day=1)


def _resolve_selected_date(selected_date_param: str | None, visible_month: date, training_plan) -> date:
    if selected_date_param:
        try:
            return date.fromisoformat(selected_date_param)
        except ValueError:
            pass

    today = date.today()
    if today.year == visible_month.year and today.month == visible_month.month:
        return today

    visible_days = [day for day in training_plan.training_days if day.day_date.year == visible_month.year and day.day_date.month == visible_month.month]
    if visible_days:
        return min(visible_days, key=lambda item: item.day_date).day_date

    if training_plan.start_date and training_plan.start_date.year == visible_month.year and training_plan.start_date.month == visible_month.month:
        return training_plan.start_date

    return visible_month


def _build_calendar_context(training_plan, visible_month: date, selected_day_date: date) -> dict[str, object]:
    calendar_weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(visible_month.year, visible_month.month)
    day_map = {training_day.day_date: training_day for training_day in training_plan.training_days}
    first_day = visible_month
    last_day = date(visible_month.year, visible_month.month, calendar.monthrange(visible_month.year, visible_month.month)[1])

    weeks: list[list[dict[str, object]]] = []
    selected_day = day_map.get(selected_day_date)
    selected_day_cell: dict[str, object] | None = None

    for week in calendar_weeks:
        cells: list[dict[str, object]] = []
        for current_day in week:
            training_day = day_map.get(current_day)
            session_count = len(training_day.planned_sessions) if training_day else 0
            group_count = len(training_day.session_groups) if training_day else 0
            matched_count = 0
            analyzed_count = 0
            session_summaries: list[dict[str, object]] = []
            primary_goals = []
            secondary_goals = []

            if training_day:
                for planned_session in training_day.planned_sessions:
                    derived_metrics = derive_session_metrics(planned_session)
                    has_match = planned_session.activity_match is not None and planned_session.activity_match.garmin_activity is not None
                    has_analysis = bool(planned_session.analysis_reports)
                    matched_count += 1 if has_match else 0
                    analyzed_count += 1 if has_analysis else 0
                    session_summaries.append(
                        {
                            "id": planned_session.id,
                            "name": planned_session.name,
                            "sport_type": planned_session.sport_type,
                            "session_type": planned_session.session_type,
                            "summary_title": describe_session_structure_short(planned_session) or derived_metrics.title or planned_session.name,
                            "expected_duration_min": planned_session.expected_duration_min,
                            "has_steps": bool(planned_session.planned_session_steps),
                            "has_group": planned_session.session_group is not None,
                            "group_name": planned_session.session_group.name if planned_session.session_group else None,
                            "has_match": has_match,
                            "has_analysis": has_analysis,
                        }
                    )
                for goal in training_plan.goals:
                    if goal.event_date != current_day:
                        continue
                    summary = {
                        "id": goal.id,
                        "name": goal.name,
                        "sport_type": goal.sport_type,
                        "priority": goal.priority,
                    }
                    if goal.goal_role == "primary":
                        primary_goals.append(summary)
                    else:
                        secondary_goals.append(summary)
            else:
                for goal in training_plan.goals:
                    if goal.event_date != current_day:
                        continue
                    summary = {
                        "id": goal.id,
                        "name": goal.name,
                        "sport_type": goal.sport_type,
                        "priority": goal.priority,
                    }
                    if goal.goal_role == "primary":
                        primary_goals.append(summary)
                    else:
                        secondary_goals.append(summary)

            cell = {
                "date": current_day,
                "is_current_month": current_day.month == visible_month.month,
                "is_today": current_day == date.today(),
                "is_selected": current_day == selected_day_date,
                "training_day": training_day,
                "session_count": session_count,
                "group_count": group_count,
                "matched_count": matched_count,
                "analyzed_count": analyzed_count,
                "primary_goals": primary_goals,
                "secondary_goals": secondary_goals,
                "session_summaries": session_summaries[:3],
                "overflow_count": max(0, len(session_summaries) - 3),
            }
            cells.append(cell)

            if current_day == selected_day_date:
                selected_day_cell = cell

        weeks.append(cells)

    previous_month = (first_day.replace(day=1) - date.resolution).replace(day=1).strftime("%Y-%m")
    next_month = (last_day + date.resolution).replace(day=1).strftime("%Y-%m")
    month_label = _month_label(visible_month)

    return {
        "weeks": weeks,
        "selected_day": selected_day,
        "selected_day_cell": selected_day_cell,
        "previous_month": previous_month,
        "next_month": next_month,
        "month_label": month_label,
    }


def _month_label(value: date) -> str:
    month_names = [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]
    return f"{month_names[value.month - 1].capitalize()} {value.year}"


def _calendar_next_action_url(training_plan_id: int, training_day_id: int, day_date: date, next_action: str) -> str:
    calendar_url = f"/training_plans/{training_plan_id}/calendar?{urlencode({'month': day_date.strftime('%Y-%m'), 'selected_date': day_date.isoformat(), 'status': 'Dia creado'})}"
    if next_action == "quick":
        return (
            f"/planned_sessions/quick?training_day_id={training_day_id}"
            f"&return_to=calendar&month={day_date.strftime('%Y-%m')}&selected_date={day_date.isoformat()}"
        )
    if next_action == "group":
        return f"/session_groups/create?training_day_id={training_day_id}"
    if next_action == "detail":
        return f"/training_days/{training_day_id}"
    if next_action == "edit":
        return f"/training_days/{training_day_id}/edit"
    return calendar_url
