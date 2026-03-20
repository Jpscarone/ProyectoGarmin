from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.daily_health_metric import DailyHealthMetricRead
from app.services.daily_health_metric_service import get_health_metric, get_health_metrics
from app.web.templates import build_templates


router = APIRouter(prefix="/health", tags=["health"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.get("", response_model=list[DailyHealthMetricRead])
def list_health_metrics(request: Request, db: Session = Depends(get_db)):
    metrics = get_health_metrics(db)
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="health/list.html",
            context={"metrics": metrics},
        )
    return metrics


@router.get("/{metric_id}", response_model=DailyHealthMetricRead)
def read_health_metric(metric_id: int, request: Request, db: Session = Depends(get_db)):
    metric = get_health_metric(db, metric_id)
    if metric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Health metric not found")
    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="health/detail.html",
            context={"metric": metric},
        )
    return metric
