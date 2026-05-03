from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import SessionLocal, get_db
from app.routers.activities import router as activities_router
from app.routers.activity_matching import router as activity_matching_router
from app.routers.analysis import router as analysis_router
from app.routers.athletes import router as athletes_router
from app.routers.garmin_health_sync import router as garmin_health_sync_router
from app.routers.garmin_sync import router as garmin_sync_router
from app.routers.goals import router as goals_router
from app.routers.health import router as health_router
from app.routers.planned_sessions import router as planned_sessions_router
from app.routers.planned_session_steps import router as planned_session_steps_router
from app.routers.session_groups import router as session_groups_router
from app.routers.session_templates import router as session_templates_router
from app.routers.training_days import router as training_days_router
from app.routers.training_plans import router as training_plans_router
from app.routers.weather_sync import router as weather_sync_router
from app.services.athlete_context import build_global_context, get_current_athlete, get_current_training_plan
from app.services.dashboard_auto_refresh_service import (
    build_dashboard_refresh_status,
    initial_dashboard_refresh_status,
    run_dashboard_auto_refresh,
)
from app.services.dashboard_service import build_dashboard_context
from app.services.training_plan_service import auto_complete_expired_training_plans, select_default_training_plan
from app.web.templates import build_templates


BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()

app = FastAPI(title=settings.app_name)
templates = build_templates(BASE_DIR)


@app.middleware("http")
async def inject_global_athlete_context(request: Request, call_next):
    if "session" not in request.scope:
        request.scope["session"] = _load_context_session(request)
    request.state.current_athlete = None
    request.state.current_training_plan = None
    request.state.active_athletes = []
    request.state.needs_athlete_selection = False
    request.state.athlete_context_message = None
    if _should_load_global_context(request):
        db = SessionLocal()
        try:
            context = build_global_context(request, db)
            request.state.current_athlete = context["current_athlete"]
            request.state.current_training_plan = context["current_training_plan"]
            request.state.active_athletes = context["active_athletes"]
            request.state.needs_athlete_selection = context["needs_athlete_selection"]
            request.state.athlete_context_message = context["athlete_context_message"]
        finally:
            db.close()
    response = await call_next(request)
    session_payload = request.scope.get("session") or {}
    response.set_cookie(
        "training_app_context",
        _dump_context_session(session_payload),
        httponly=True,
        samesite="lax",
    )
    return response


def _should_load_global_context(request: Request) -> bool:
    path = request.url.path
    if path.startswith("/static"):
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "*/*" in accept


def _load_context_session(request: Request) -> dict[str, int]:
    raw_value = request.cookies.get("training_app_context") or ""
    session: dict[str, int] = {}
    for item in raw_value.split("|"):
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        if key not in {"current_athlete_id", "current_training_plan_id"}:
            continue
        try:
            session[key] = int(value)
        except ValueError:
            continue
    return session


def _dump_context_session(session: dict) -> str:
    values = []
    for key in ("current_athlete_id", "current_training_plan_id"):
        value = session.get(key)
        if value is None:
            continue
        try:
            values.append(f"{key}:{int(value)}")
        except (TypeError, ValueError):
            continue
    return "|".join(values)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(activities_router)
app.include_router(activity_matching_router)
app.include_router(analysis_router)
app.include_router(athletes_router)
app.include_router(health_router)
app.include_router(garmin_health_sync_router)
app.include_router(garmin_sync_router)
app.include_router(goals_router)
app.include_router(training_plans_router)
app.include_router(training_days_router)
app.include_router(planned_sessions_router)
app.include_router(planned_session_steps_router)
app.include_router(session_groups_router)
app.include_router(session_templates_router)
app.include_router(weather_sync_router)


def _coerce_dashboard_date(value: str | None) -> tuple[date, bool]:
    if not value:
        return date.today(), False
    try:
        return date.fromisoformat(value), False
    except ValueError:
        return date.today(), True


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    selected_date_value, invalid_selected_date = _coerce_dashboard_date(selected_date)
    athlete = get_current_athlete(request, db)
    if athlete is None:
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "app_name": settings.app_name,
                "dashboard": None,
                "selected_date": selected_date_value,
                "prev_date_iso": (selected_date_value - date.resolution).isoformat(),
                "next_date_iso": (selected_date_value + date.resolution).isoformat(),
                "today_date_iso": date.today().isoformat(),
                "ui_status": "La fecha seleccionada no era valida. Se mostro hoy." if invalid_selected_date else None,
                "refresh_status": None,
            },
        )

    training_plan = get_current_training_plan(request, db, athlete)
    dashboard_context = build_dashboard_context(
        db,
        athlete,
        training_plan,
        selected_date=selected_date_value,
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.app_name,
            "dashboard": dashboard_context,
            "selected_date": selected_date_value,
            "ui_status": "La fecha seleccionada no era valida. Se mostro hoy." if invalid_selected_date else None,
            "refresh_status": initial_dashboard_refresh_status(),
        },
    )


@app.post("/dashboard/auto-refresh", response_class=HTMLResponse)
async def dashboard_auto_refresh(
    request: Request,
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    selected_date_value, _ = _coerce_dashboard_date(selected_date)
    athlete = get_current_athlete(request, db)
    if athlete is None:
        return templates.TemplateResponse(
            request=request,
            name="dashboard/_auto_refresh_status.html",
            context={
                "refresh_status": {
                    "phase": "warning",
                    "message": "Seleccioná un atleta para actualizar el dashboard.",
                    "steps": [],
                }
            },
        )

    training_plan = get_current_training_plan(request, db, athlete)
    try:
        refresh_result = run_dashboard_auto_refresh(
            db,
            athlete,
            training_plan,
            selected_date_value,
        )
    except Exception:
        refresh_result = {
            "ok": False,
            "updated": False,
            "steps": [
                {
                    "key": "dashboard_refresh",
                    "status": "failed",
                    "message": "No se pudo ejecutar la actualización automática.",
                }
            ],
            "errors": ["No se pudo ejecutar la actualización automática."],
        }
    dashboard_context = build_dashboard_context(
        db,
        athlete,
        training_plan,
        selected_date=selected_date_value,
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_refresh_region.html",
        context={
            "dashboard": dashboard_context,
            "refresh_status": build_dashboard_refresh_status(refresh_result),
        },
    )


@app.get("/calendar")
def open_calendar(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    today = date.today()
    auto_complete_expired_training_plans(db, today)
    athlete = get_current_athlete(request, db)
    if athlete is None:
        return RedirectResponse(url="/athletes/select", status_code=303)
    selected_plan = get_current_training_plan(request, db, athlete) or select_default_training_plan(db, athlete_id=athlete.id, today=today)
    if selected_plan is None:
        return RedirectResponse(url="/training_plans", status_code=303)

    return RedirectResponse(
        url=(
            f"/training_plans/{selected_plan.id}/calendar"
            f"?athlete_id={athlete.id}&month={today.strftime('%Y-%m')}&selected_date={today.isoformat()}"
        ),
        status_code=303,
    )
