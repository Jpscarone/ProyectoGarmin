from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.garmin_activity import GarminActivityDetailRead, GarminActivityRead
from app.services.analysis.report_service import get_latest_activity_report
from app.services.garmin_activity_service import get_activities, get_activity
from app.web.templates import build_templates


router = APIRouter(prefix="/activities", tags=["activities"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[GarminActivityRead])
def list_activities(request: Request, db: Session = Depends(get_db)):
    activities = get_activities(db)
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="activities/list.html",
            context={
                "activities": activities,
                "weather_status": request.query_params.get("weather_status"),
                "match_status": request.query_params.get("match_status"),
            },
        )
    return activities


@router.get("/{activity_id}", response_model=GarminActivityDetailRead)
def read_activity(activity_id: int, request: Request, db: Session = Depends(get_db)):
    activity = get_activity(db, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="activities/detail.html",
            context={
                "activity": activity,
                "latest_report": get_latest_activity_report(db, activity.id),
                "weather_status": request.query_params.get("weather_status"),
                "match_status": request.query_params.get("match_status"),
                "analysis_status": request.query_params.get("analysis_status"),
            },
        )
    return activity
