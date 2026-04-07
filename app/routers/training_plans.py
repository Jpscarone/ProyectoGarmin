from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.weekly_analysis import WeeklyAnalysis
from app.db.session import get_db
from app.schemas.training_day import TrainingDayCreate
from app.schemas.training_plan import TrainingPlanCreate, TrainingPlanRead, TrainingPlanUpdate
from app.services.analysis_v2.weekly_analysis_service import ANALYSIS_VERSION as WEEKLY_ANALYSIS_VERSION
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
    selected_week_analysis = _build_selected_week_analysis_context(db, training_plan, selected_day_date, visible_month)
    weekly_analysis_lookup = _build_weekly_analysis_lookup(db, training_plan, calendar_context["weeks"], visible_month)

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
            "selected_week_analysis": selected_week_analysis,
            "weekly_analysis_lookup": weekly_analysis_lookup,
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

    visible_month_days = [
        day.day_date
        for day in training_plan.training_days
        if day.day_date.year == visible_month.year and day.day_date.month == visible_month.month
    ]
    if visible_month_days:
        return min(visible_month_days)

    return visible_month


def _week_start(day_value: date) -> date:
    return day_value - timedelta(days=day_value.weekday())


def _week_end(day_value: date) -> date:
    return _week_start(day_value) + timedelta(days=6)


def _get_weekly_analysis_for_range(db: Session, athlete_id: int, week_start_date: date) -> WeeklyAnalysis | None:
    return db.scalar(
        select(WeeklyAnalysis)
        .where(
            WeeklyAnalysis.athlete_id == athlete_id,
            WeeklyAnalysis.week_start_date == week_start_date,
            WeeklyAnalysis.analysis_version == WEEKLY_ANALYSIS_VERSION,
        )
        .order_by(WeeklyAnalysis.id.desc())
    )


def _build_selected_week_analysis_context(db: Session, training_plan, selected_day_date: date, visible_month: date) -> dict[str, object]:
    return _build_week_analysis_link(db, training_plan, selected_day_date, visible_month)


def _build_week_analysis_link(db: Session, training_plan, selected_date: date, visible_month: date) -> dict[str, object]:
    week_start_date = _week_start(selected_date)
    week_end_date = _week_end(selected_date)
    analysis = _get_weekly_analysis_for_range(db, training_plan.athlete_id, week_start_date)
    badge = _weekly_calendar_badge_view(analysis)
    query = urlencode(
        {
            "return_to": "calendar",
            "plan_id": training_plan.id,
            "month": visible_month.strftime("%Y-%m"),
            "selected_date": selected_date.isoformat(),
        }
    )
    return {
        "selected_date": selected_date.isoformat(),
        "week_start_date": week_start_date.isoformat(),
        "week_end_date": week_end_date.isoformat(),
        "week_range_label": f"{week_start_date.strftime('%d/%m')} al {week_end_date.strftime('%d/%m/%Y')}",
        "url": f"/analysis/weekly/{training_plan.athlete_id}/{week_start_date.isoformat()}?{query}",
        "exists": analysis is not None,
        "status": analysis.status if analysis else "missing",
        "status_label": badge["label"],
        "status_class": badge["class"],
    }


def _build_weekly_analysis_lookup(db: Session, training_plan, weeks: list[list[dict[str, object]]], visible_month: date) -> dict[str, dict[str, object]]:
    lookup: dict[str, dict[str, object]] = {}
    seen_week_starts: set[date] = set()
    for week in weeks:
        if not week:
            continue
        first_cell_date = week[0].get("date")
        if not isinstance(first_cell_date, date):
            continue
        week_start_date = _week_start(first_cell_date)
        if week_start_date in seen_week_starts:
            continue
        seen_week_starts.add(week_start_date)
        lookup[week_start_date.isoformat()] = _build_week_analysis_link(db, training_plan, week_start_date, visible_month)
    return lookup


def _weekly_calendar_badge_view(analysis: WeeklyAnalysis | None) -> dict[str, str]:
    if analysis is None:
        return {"label": "Sin analisis", "class": "calendar-state-badge-empty"}

    if analysis.status == "error":
        return {"label": "Semana irregular", "class": "calendar-state-badge-failed"}
    if analysis.status == "pending":
        return {"label": "Analisis pendiente", "class": "calendar-state-badge-info"}

    metrics_payload = analysis.metrics_json if isinstance(analysis.metrics_json, dict) else {}
    metrics = metrics_payload.get("metrics", {}) if isinstance(metrics_payload, dict) else {}
    derived_flags = metrics.get("derived_flags", {}) if isinstance(metrics, dict) else {}

    if (
        derived_flags.get("overload_flag")
        or derived_flags.get("high_fatigue_risk_flag")
        or (analysis.fatigue_score is not None and analysis.fatigue_score >= 75)
    ):
        return {"label": "Semana exigente", "class": "calendar-state-badge-partial"}

    if (
        analysis.status == "completed"
        and (analysis.consistency_score is None or analysis.consistency_score >= 75)
        and (analysis.balance_score is None or analysis.balance_score >= 70)
        and (analysis.load_score is None or analysis.load_score >= 70)
        and (analysis.fatigue_score is None or analysis.fatigue_score < 75)
        and not derived_flags.get("poor_distribution_flag")
        and not derived_flags.get("low_consistency_flag")
    ):
        return {"label": "Semana sólida", "class": "calendar-state-badge-success"}

    if (
        analysis.status in {"completed", "completed_with_warnings"}
        and not derived_flags.get("poor_distribution_flag")
        and not derived_flags.get("undertraining_flag")
        and not derived_flags.get("overload_flag")
    ):
        return {"label": "Semana correcta", "class": "calendar-state-badge-info"}

    return {"label": "Semana irregular", "class": "calendar-state-badge-failed"}


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
                day_status, day_status_label = _resolve_calendar_day_status(training_day)
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
                            "compact_label": _calendar_session_compact_label(planned_session, derived_metrics),
                            "expected_duration_min": planned_session.expected_duration_min,
                            "has_steps": bool(planned_session.planned_session_steps),
                            "has_group": planned_session.session_group is not None,
                            "group_name": planned_session.session_group.name if planned_session.session_group else None,
                            "has_match": has_match,
                            "has_analysis": has_analysis,
                            "description": (planned_session.description_text or planned_session.target_notes or "").strip(),
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
                day_status, day_status_label = ("empty", "Sin actividad")
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
                "day_status": day_status,
                "day_status_label": day_status_label,
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


def _resolve_calendar_day_status(training_day) -> tuple[str, str]:
    day_reports = [report for report in training_day.analysis_reports if report.report_type == "day_summary"]
    latest_day_report = max(day_reports, key=lambda report: report.generated_at) if day_reports else None
    if latest_day_report is not None:
        status = latest_day_report.overall_status
        mapping = {
            "correct": ("correct", "Correcto"),
            "partial": ("partial", "Parcial"),
            "failed": ("failed", "No completado"),
            "not_completed": ("failed", "No completado"),
            "review": ("empty", "Revisar"),
            "skipped": ("empty", "Sin actividad"),
        }
        return mapping.get(status, ("empty", "Sin actividad"))

    session_reports = []
    for planned_session in training_day.planned_sessions:
        session_reports.extend([report for report in planned_session.analysis_reports if report.report_type == "session"])
    if not session_reports:
        return ("empty", "Sin actividad")

    statuses = {report.overall_status for report in session_reports}
    if "correct" in statuses and statuses <= {"correct"}:
        return ("correct", "Correcto")
    if statuses & {"failed", "not_completed"}:
        return ("failed", "No completado")
    if "partial" in statuses:
        return ("partial", "Parcial")
    return ("empty", "Revisar")


def _calendar_session_compact_label(planned_session, derived_metrics) -> str:
    sport = _calendar_sport_icon(planned_session.sport_type)
    title = _calendar_short_title(planned_session)
    metric = "-"
    if derived_metrics.duration_sec:
        metric = _duration_from_seconds_short(derived_metrics.duration_sec)
    elif derived_metrics.distance_m:
        metric = _distance_from_meters_short(derived_metrics.distance_m)
    return f"{sport} {title} - {metric}".strip()


def _calendar_sport_icon(sport_type: str | None) -> str:
    mapping = {
        "running": "RUN",
        "trail_running": "TRAIL",
        "cycling": "BIKE",
        "mtb": "MTB",
        "swimming": "SWIM",
        "multisport": "MULTI",
    }
    return mapping.get(sport_type or "", "SES")


def _calendar_short_title(planned_session) -> str:
    if planned_session.target_hr_zone:
        return planned_session.target_hr_zone
    if planned_session.target_power_zone:
        return planned_session.target_power_zone
    if planned_session.session_type:
        labels = {
            "easy": "Suave",
            "base": "Base",
            "long": "Fondo",
            "tempo": "Tempo",
            "hard": "Fuerte",
            "technique": "Tecnica",
            "recovery": "Recup",
            "race": "Carrera",
            "intervals": "Series",
        }
        return labels.get(planned_session.session_type, planned_session.session_type.title())
    return (planned_session.name or "Sesion")[:18].strip()


def _duration_from_seconds_short(value: int) -> str:
    total_minutes = round(value / 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h" if minutes == 0 else f"{hours}h{minutes:02d}"
    return f"{minutes}min"


def _distance_from_meters_short(value: int) -> str:
    if value >= 1000:
        km_value = value / 1000
        if km_value.is_integer():
            return f"{int(km_value)}km"
        return f"{km_value:.1f}km"
    return f"{int(value)}m"


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
