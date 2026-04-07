from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
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
from app.services.training_plan_service import get_training_plans
from app.web.templates import build_templates


BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()

app = FastAPI(title=settings.app_name)
templates = build_templates(BASE_DIR)

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


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"app_name": settings.app_name},
    )


@app.get("/calendar")
def open_calendar(db: Session = Depends(get_db)) -> RedirectResponse:
    plans = get_training_plans(db)
    if not plans:
        return RedirectResponse(url="/training_plans", status_code=303)

    today = date.today()
    current_plans = [
        plan
        for plan in plans
        if plan.start_date is not None
        and plan.end_date is not None
        and plan.start_date <= today <= plan.end_date
    ]
    if current_plans:
        selected_plan = max(current_plans, key=lambda plan: (plan.start_date, plan.id))
    else:
        selected_plan = plans[0]

    return RedirectResponse(
        url=(
            f"/training_plans/{selected_plan.id}/calendar"
            f"?month={today.strftime('%Y-%m')}&selected_date={today.isoformat()}"
        ),
        status_code=303,
    )
