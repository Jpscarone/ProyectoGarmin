from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.analysis.bundle_service import (
    build_bundle_for_activity,
    build_bundle_for_report,
    build_bundle_for_session,
)
from app.services.analysis.report_service import (
    analyze_activity,
    analyze_session,
    analyze_training_day,
    get_analysis_report,
    update_final_conclusion,
)
from app.web.templates import build_templates


router = APIRouter(prefix="/analysis", tags=["analysis"])
templates = build_templates(Path(__file__).resolve().parent.parent)


@router.get("/{report_id}", response_class=HTMLResponse)
def read_analysis_report(report_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    report = get_analysis_report(db, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis report not found")
    return templates.TemplateResponse(
        request=request,
        name="analysis/detail.html",
        context={"report": report, "status_message": request.query_params.get("status")},
    )


@router.post("/session/{planned_session_id}")
def analyze_session_endpoint(planned_session_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        report = analyze_session(db, planned_session_id)
        return RedirectResponse(url=f"/analysis/{report.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/planned_sessions/{planned_session_id}?analysis_status={quote(str(exc))}",
            status_code=303,
        )


@router.post("/activity/{activity_id}")
def analyze_activity_endpoint(activity_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        report = analyze_activity(db, activity_id)
        return RedirectResponse(url=f"/analysis/{report.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/activities/{activity_id}?analysis_status={quote(str(exc))}",
            status_code=303,
        )


@router.post("/day/{training_day_id}")
def analyze_day_endpoint(training_day_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        report = analyze_training_day(db, training_day_id)
        return RedirectResponse(url=f"/analysis/{report.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/training_days/{training_day_id}?analysis_status={quote(str(exc))}",
            status_code=303,
        )


@router.post("/{report_id}/conclusion")
def save_final_conclusion(
    report_id: int,
    final_conclusion_text: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    report = get_analysis_report(db, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis report not found")
    update_final_conclusion(db, report, final_conclusion_text)
    return RedirectResponse(
        url=f"/analysis/{report_id}?status={quote('Conclusion final guardada.')}",
        status_code=303,
    )


@router.get("/bundle/session/{planned_session_id}", response_class=HTMLResponse)
def session_bundle_view(planned_session_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        bundle = build_bundle_for_session(db, planned_session_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="analysis/bundle.html",
        context={"bundle": bundle, "back_url": f"/planned_sessions/{planned_session_id}"},
    )


@router.get("/bundle/activity/{activity_id}", response_class=HTMLResponse)
def activity_bundle_view(activity_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        bundle = build_bundle_for_activity(db, activity_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="analysis/bundle.html",
        context={"bundle": bundle, "back_url": f"/activities/{activity_id}"},
    )


@router.get("/bundle/report/{report_id}", response_class=HTMLResponse)
def report_bundle_view(report_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        bundle = build_bundle_for_report(db, report_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="analysis/bundle.html",
        context={"bundle": bundle, "back_url": f"/analysis/{report_id}"},
    )
