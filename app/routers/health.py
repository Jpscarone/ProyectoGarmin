from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.athlete import Athlete
from app.db.session import get_db
from app.config import get_settings
from app.schemas.daily_health_metric import DailyHealthMetricRead
from app.services.daily_health_metric_service import get_health_metric, get_health_metrics
from app.services.athlete_context import get_current_athlete
from app.services.health_ai_analysis_service import (
    analyze_health_readiness_with_ai,
    build_health_llm_json_hash,
    create_health_ai_analysis,
    get_latest_health_ai_analysis_for_date,
    list_health_ai_analyses_for_athlete,
    should_auto_run_health_ai_analysis,
)
from app.services.health_auto_sync_service import (
    build_health_sync_view,
    get_health_sync_state,
    run_health_auto_sync,
    serialize_health_sync_state,
    should_auto_sync_health,
    utc_now,
)
from app.services.health_readiness_service import (
    build_health_llm_json,
    build_health_readiness_summary,
    build_health_training_context,
    evaluate_health_readiness,
)
from app.services.openai_client import OpenAIIntegrationError, get_openai_model
from app.web.templates import build_templates


router = APIRouter(prefix="/health", tags=["health"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


def _coerce_selected_date(value: str | None) -> tuple[date, bool]:
    if not value:
        return date.today(), False
    try:
        return date.fromisoformat(value), False
    except ValueError:
        return date.today(), True


def _resolve_health_athlete(db: Session, athlete_id: int | None, metrics: list[Any]) -> Athlete | None:
    if athlete_id is not None:
        return db.get(Athlete, athlete_id)
    # Fallback legacy: only infer from metrics when there is a single athlete represented.
    metric_athlete_ids = {metric.athlete_id for metric in metrics if getattr(metric, "athlete_id", None)}
    if len(metric_athlete_ids) == 1:
        return db.get(Athlete, next(iter(metric_athlete_ids)))
    return db.scalar(select(Athlete).order_by(Athlete.created_at.asc(), Athlete.id.asc()))


def _health_readiness_status_class(status: str) -> str:
    mapping = {
        "green": "health-readiness-status-green",
        "yellow": "health-readiness-status-yellow",
        "orange": "health-readiness-status-orange",
        "red": "health-readiness-status-red",
        "insufficient_data": "health-readiness-status-insufficient",
    }
    return mapping.get(status, "health-readiness-status-insufficient")


def _health_readiness_score_label(score: int | None) -> str:
    return "-" if score is None else f"{score}/100"


def _build_health_metric_overview(summary: Any) -> list[dict[str, str]]:
    return [
        {"label": "Sueno promedio 7d", "value": _hours_label(summary.sleep_avg_7d)},
        {"label": "FC reposo 3d vs 14d", "value": _resting_hr_delta_label(summary.resting_hr_avg_3d, summary.resting_hr_avg_14d, summary.resting_hr_delta_3d_vs_14d)},
        {"label": "HRV tendencia", "value": _hrv_trend_label(summary.hrv_trend)},
        {"label": "Estres 3d", "value": _number_label(summary.stress_avg_3d)},
        {"label": "Body Battery manana 3d", "value": _number_label(summary.body_battery_morning_avg_3d)},
        {"label": "Dias disponibles 14d", "value": f"{summary.available_days_14d}/14"},
    ]


def _serialize_health_ai_analysis(analysis: Any | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id,
        "reference_date": analysis.reference_date.isoformat(),
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "created_at_label": analysis.created_at.strftime("%d/%m/%Y %H:%M") if analysis.created_at else None,
        "summary": analysis.summary,
        "training_recommendation": analysis.training_recommendation,
        "risk_level": analysis.risk_level,
        "model_name": analysis.model_name,
        "llm_json_hash": analysis.llm_json_hash,
        "main_factors": list((analysis.ai_response_json or {}).get("main_factors") or []),
        "what_to_watch": list((analysis.ai_response_json or {}).get("what_to_watch") or []),
        "not_medical_advice": bool((analysis.ai_response_json or {}).get("not_medical_advice", True)),
    }


def _serialize_health_ai_analysis_history(analyses: list[Any], athlete_id: int | None) -> list[dict[str, Any]]:
    history_rows: list[dict[str, Any]] = []
    for analysis in analyses:
        llm_json = analysis.llm_json or {}
        readiness_local = llm_json.get("readiness_local") or {}
        history_rows.append(
            {
                "id": analysis.id,
                "reference_date": analysis.reference_date.isoformat(),
                "reference_date_label": analysis.reference_date.strftime("%d/%m/%Y"),
                "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
                "created_at_label": analysis.created_at.strftime("%d/%m/%Y %H:%M") if analysis.created_at else None,
                "readiness_status": readiness_local.get("readiness_status"),
                "readiness_status_label": readiness_local.get("readiness_label") or readiness_local.get("readiness_status") or "-",
                "readiness_status_class": _health_readiness_status_class(readiness_local.get("readiness_status") or "insufficient_data"),
                "readiness_score": readiness_local.get("readiness_score"),
                "risk_level": analysis.risk_level or "unknown",
                "risk_level_label": (analysis.risk_level or "unknown").replace("_", " "),
                "summary": analysis.summary or "-",
                "view_date_url": (
                    "/health?"
                    + "&".join(
                        part
                        for part in [
                            f"selected_date={analysis.reference_date.isoformat()}",
                            f"athlete_id={athlete_id}" if athlete_id is not None else "",
                        ]
                        if part
                    )
                ),
            }
        )
    return history_rows


def _serialize_health_ai_analysis_trend(analyses: list[Any]) -> dict[str, Any]:
    trend_points: list[dict[str, Any]] = []
    for analysis in analyses:
        llm_json = analysis.llm_json or {}
        readiness_local = llm_json.get("readiness_local") or {}
        readiness_score = readiness_local.get("readiness_score")
        if readiness_score is None:
            continue
        try:
            score_value = int(readiness_score)
        except (TypeError, ValueError):
            continue

        trend_points.append(
            {
                "reference_date": analysis.reference_date.isoformat(),
                "reference_date_label": analysis.reference_date.strftime("%d/%m"),
                "readiness_score": max(0, min(100, score_value)),
                "readiness_status": readiness_local.get("readiness_status") or "insufficient_data",
                "readiness_status_label": readiness_local.get("readiness_label") or readiness_local.get("readiness_status") or "-",
                "readiness_status_class": _health_readiness_status_class(readiness_local.get("readiness_status") or "insufficient_data"),
                "risk_level": analysis.risk_level or "unknown",
                "risk_level_label": (analysis.risk_level or "unknown").replace("_", " "),
            }
        )

    trend_points = list(reversed(trend_points))
    return {
        "points": trend_points,
        "has_enough_points": len(trend_points) >= 2,
    }


def _build_training_context_view(training_context: dict[str, Any]) -> dict[str, Any]:
    next_goal = training_context.get("next_goal_name")
    days_to_goal = training_context.get("days_to_next_goal")
    items = [
        {"label": "Actividades 7d", "value": str(training_context.get("completed_activities_last_7d") or 0)},
        {"label": "Sesiones planificadas 7d", "value": str(training_context.get("planned_sessions_last_7d") or 0)},
        {"label": "Sesiones duras 7d", "value": str(training_context.get("hard_sessions_last_7d") or 0)},
        {"label": "Ultima actividad", "value": _date_iso_label(training_context.get("last_activity_date"))},
        {"label": "Ultimo entrenamiento duro", "value": _date_iso_label(training_context.get("last_hard_session_date"))},
        {"label": "Minutos totales 7d", "value": _number_label(training_context.get("total_duration_minutes_last_7d"))},
        {"label": "Km totales 7d", "value": _number_label(training_context.get("total_distance_km_last_7d"))},
    ]
    if next_goal:
        items.append({"label": "Proximo objetivo", "value": str(next_goal)})
        items.append({"label": "Dias al objetivo", "value": _number_label(days_to_goal)})

    has_recent_data = any(
        [
            (training_context.get("completed_activities_last_7d") or 0) > 0,
            (training_context.get("planned_sessions_last_7d") or 0) > 0,
            bool(training_context.get("last_activity_date")),
            bool(next_goal),
        ]
    )
    return {
        "has_recent_data": has_recent_data,
        "metric_items": items,
    }


def _build_health_readiness_view_model(
    db: Session,
    *,
    athlete_id: int | None,
    selected_date: date,
    metrics: list[Any] | None = None,
) -> dict[str, Any]:
    metric_rows = metrics if metrics is not None else get_health_metrics(db)
    athlete = _resolve_health_athlete(db, athlete_id, metric_rows)

    if athlete is None:
        return {
            "athlete_id": None,
            "athlete_name": None,
            "selected_date": selected_date.isoformat(),
            "summary": None,
            "evaluation": {
                "readiness_score": None,
                "readiness_status": "insufficient_data",
                "readiness_label": "datos insuficientes",
                "main_limiter": None,
                "reasons": [],
                "recommendation": "Todavia no hay datos suficientes para evaluar la tendencia. Hacen falta al menos 5 dias dentro de los ultimos 14.",
                "data_quality": "poor",
                "data_quality_reasons": ["Todavia no hay un atleta o metricas diarias disponibles para construir la tendencia."],
            },
            "status_class": _health_readiness_status_class("insufficient_data"),
            "score_label": "-",
            "main_limiter_label": None,
            "reason_items": [],
            "metric_overview": [],
            "sync_state": None,
            "sync_view": build_health_sync_view(None, should_auto_sync=False),
            "should_auto_sync": False,
            "health_auto_sync_url": "",
        }

    summary = build_health_readiness_summary(db, athlete.id, selected_date)
    evaluation = evaluate_health_readiness(summary)
    training_context = build_health_training_context(db, athlete.id, selected_date)
    latest_ai_analysis = get_latest_health_ai_analysis_for_date(db, athlete.id, selected_date)
    recent_ai_analyses = list_health_ai_analyses_for_athlete(db, athlete.id, limit=10)
    sync_state = get_health_sync_state(db, athlete.id)
    should_sync = should_auto_sync_health(sync_state, utc_now(), selected_date)
    today = date.today()

    def build_health_url(target_date: date) -> str:
        query = [f"selected_date={target_date.isoformat()}"]
        if athlete.id is not None:
            query.append(f"athlete_id={athlete.id}")
        return "/health?" + "&".join(query)

    return {
        "athlete_id": athlete.id,
        "athlete_name": athlete.name,
        "selected_date": selected_date.isoformat(),
        "selected_date_label": selected_date.strftime("%d/%m/%Y"),
        "quick_nav": {
            "yesterday_url": build_health_url(selected_date - timedelta(days=1)),
            "minus_7d_url": build_health_url(selected_date - timedelta(days=7)),
            "plus_1d_url": None if selected_date >= today else build_health_url(selected_date + timedelta(days=1)),
            "today_url": build_health_url(today),
            "is_today": selected_date == today,
        },
        "summary": summary.model_dump(),
        "evaluation": evaluation.model_dump(),
        "status_class": _health_readiness_status_class(evaluation.readiness_status),
        "score_label": _health_readiness_score_label(evaluation.readiness_score),
        "main_limiter_label": _main_limiter_label(evaluation.main_limiter),
        "reason_items": evaluation.reasons[:3],
        "metric_overview": _build_health_metric_overview(summary),
        "training_context": training_context,
        "training_context_view": _build_training_context_view(training_context),
        "sync_state": serialize_health_sync_state(sync_state),
        "sync_view": build_health_sync_view(sync_state, should_auto_sync=should_sync),
        "should_auto_sync": should_sync,
        "health_auto_sync_url": f"/health/auto-sync?selected_date={selected_date.isoformat()}&athlete_id={athlete.id}",
        "latest_ai_analysis": _serialize_health_ai_analysis(latest_ai_analysis),
        "recent_ai_history": _serialize_health_ai_analysis_history(recent_ai_analyses[:5], athlete.id),
        "recent_ai_trend": _serialize_health_ai_analysis_trend(recent_ai_analyses),
    }


def _hours_label(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f} h"


def _number_label(value: float | None) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _date_iso_label(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def _resting_hr_delta_label(avg_3d: float | None, avg_14d: float | None, delta: float | None) -> str:
    if avg_3d is None or avg_14d is None or delta is None:
        return "-"
    sign = "+" if delta > 0 else ""
    return f"{_number_label(avg_3d)} vs {_number_label(avg_14d)} ({sign}{delta:.1f})"


def _hrv_trend_label(value: str | None) -> str:
    mapping = {
        "up": "subiendo",
        "down": "bajando",
        "stable": "estable",
        "insufficient_data": "sin datos suficientes",
    }
    return mapping.get(value or "", "-")


def _main_limiter_label(value: str | None) -> str | None:
    mapping = {
        "hrv": "HRV",
        "resting_hr": "FC reposo",
        "sleep": "Sueno",
        "body_battery": "Body Battery",
        "stress": "Estres",
    }
    return mapping.get(value or "")


@router.get("", response_model=list[DailyHealthMetricRead])
def list_health_metrics(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = None,
    db: Session = Depends(get_db),
):
    metrics = get_health_metrics(db)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is None and _wants_html(request):
        return RedirectResponse(url="/athletes/select", status_code=303)
    if current_athlete is not None:
        athlete_id = current_athlete.id
        metrics = [metric for metric in metrics if metric.athlete_id == current_athlete.id]
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    readiness_view = _build_health_readiness_view_model(
        db,
        athlete_id=athlete_id,
        selected_date=selected_date_value,
        metrics=metrics,
    )
    if _wants_html(request):
        ui_status = request.query_params.get("ui_status")
        if invalid_selected_date:
            ui_status = "La fecha seleccionada no era valida. Se mostro el estado de hoy."
        return templates.TemplateResponse(
            request=request,
            name="health/list.html",
            context={
                "metrics": metrics,
                "readiness": readiness_view,
                "ui_status": ui_status,
            },
        )
    return metrics


@router.get("/readiness")
def read_health_readiness(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
    if invalid_selected_date:
        return {
            "error": "invalid_selected_date",
            "message": "selected_date debe tener formato YYYY-MM-DD.",
            "fallback_date": selected_date_value.isoformat(),
            "readiness": _build_health_readiness_view_model(
                db,
                athlete_id=athlete_id,
                selected_date=selected_date_value,
            ),
        }
    return _build_health_readiness_view_model(
        db,
        athlete_id=athlete_id,
        selected_date=selected_date_value,
    )


@router.post("/auto-sync")
def auto_sync_health(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
    athlete = _resolve_health_athlete(db, athlete_id, get_health_metrics(db))
    if athlete is None:
        return JSONResponse(
            status_code=404,
            content={
                "synced": False,
                "reason": "athlete_not_found",
                "message": "No se encontro un atleta para sincronizar salud.",
            },
        )

    result = run_health_auto_sync(
        db,
        athlete_id=athlete.id,
        settings=get_settings(),
        reference_date=selected_date_value,
        force=force,
    )
    if invalid_selected_date:
        result["warning"] = "selected_date invalida; se uso la fecha de hoy."
    return result


@router.get("/readiness/llm-json")
def read_health_readiness_llm_json(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
    athlete = _resolve_health_athlete(db, athlete_id, get_health_metrics(db))
    if athlete is None:
        return {
            "error": "athlete_not_found",
            "message": "No se encontro un atleta para construir el JSON de salud.",
        }

    summary = build_health_readiness_summary(db, athlete.id, selected_date_value)
    evaluation = evaluate_health_readiness(summary)
    training_context = build_health_training_context(db, athlete.id, selected_date_value)
    payload = build_health_llm_json(
        athlete,
        summary,
        evaluation,
        selected_date_value,
        training_context=training_context,
    )
    if invalid_selected_date:
        return {
            "error": "invalid_selected_date",
            "message": "selected_date debe tener formato YYYY-MM-DD.",
            "fallback_date": selected_date_value.isoformat(),
            "payload": payload,
        }
    return payload


@router.post("/readiness/ai-analysis")
def analyze_health_readiness(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
    athlete = _resolve_health_athlete(db, athlete_id, get_health_metrics(db))
    if athlete is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "athlete_not_found",
                "message": "No se encontro un atleta para analizar readiness.",
            },
        )

    summary = build_health_readiness_summary(db, athlete.id, selected_date_value)
    evaluation = evaluate_health_readiness(summary)
    training_context = build_health_training_context(db, athlete.id, selected_date_value)
    llm_json = build_health_llm_json(
        athlete,
        summary,
        evaluation,
        selected_date_value,
        training_context=training_context,
    )
    llm_json_hash = build_health_llm_json_hash(llm_json)

    try:
        analysis = analyze_health_readiness_with_ai(llm_json)
    except OpenAIIntegrationError as exc:
        error_code = "missing_api_key" if "api_key" in str(exc).lower() else "ai_analysis_failed"
        status_code = 503 if error_code == "missing_api_key" else 502
        return JSONResponse(
            status_code=status_code,
            content={
                "error": error_code,
                "message": str(exc),
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": "ai_analysis_failed",
                "message": f"No se pudo analizar readiness con IA: {exc}",
            },
        )

    model_name = None
    try:
        model_name = get_openai_model(get_settings())
    except Exception:
        model_name = None

    saved_analysis = create_health_ai_analysis(
        db,
        athlete_id=athlete.id,
        reference_date=selected_date_value,
        llm_json=llm_json,
        ai_response_json=analysis,
        summary=analysis.get("summary"),
        training_recommendation=analysis.get("training_recommendation"),
        risk_level=analysis.get("risk_level"),
        model_name=model_name,
        llm_json_hash=llm_json_hash,
    )

    response_payload: dict[str, Any] = {
        "selected_date": selected_date_value.isoformat(),
        "llm_json": llm_json,
        "analysis": analysis,
        "saved_analysis": _serialize_health_ai_analysis(saved_analysis),
    }
    if invalid_selected_date:
        response_payload["warning"] = "selected_date invalida; se uso la fecha de hoy."
    return response_payload


@router.post("/readiness/auto-ai-analysis")
def auto_analyze_health_readiness(
    request: Request,
    athlete_id: int | None = None,
    selected_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    selected_date_value, invalid_selected_date = _coerce_selected_date(selected_date)
    current_athlete = get_current_athlete(request, db, athlete_id=athlete_id)
    if current_athlete is not None:
        athlete_id = current_athlete.id
    athlete = _resolve_health_athlete(db, athlete_id, get_health_metrics(db))
    if athlete is None:
        return JSONResponse(
            status_code=404,
            content={
                "ran": False,
                "reason": "athlete_not_found",
                "message": "No se encontro un atleta para analizar readiness.",
            },
        )

    summary = build_health_readiness_summary(db, athlete.id, selected_date_value)
    evaluation = evaluate_health_readiness(summary)
    training_context = build_health_training_context(db, athlete.id, selected_date_value)
    llm_json = build_health_llm_json(
        athlete,
        summary,
        evaluation,
        selected_date_value,
        training_context=training_context,
    )
    llm_json_hash = build_health_llm_json_hash(llm_json)
    latest_analysis = get_latest_health_ai_analysis_for_date(db, athlete.id, selected_date_value)

    if not should_auto_run_health_ai_analysis(latest_analysis, llm_json_hash):
        return {
            "ran": False,
            "reason": "already_analyzed",
            "latest_analysis": _serialize_health_ai_analysis(latest_analysis),
        }

    try:
        analysis = analyze_health_readiness_with_ai(llm_json)
    except OpenAIIntegrationError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ran": False,
                "reason": "ai_analysis_failed",
                "message": str(exc),
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ran": False,
                "reason": "ai_analysis_failed",
                "message": f"No se pudo analizar readiness con IA: {exc}",
            },
        )

    model_name = None
    try:
        model_name = get_openai_model(get_settings())
    except Exception:
        model_name = None

    saved_analysis = create_health_ai_analysis(
        db,
        athlete_id=athlete.id,
        reference_date=selected_date_value,
        llm_json=llm_json,
        llm_json_hash=llm_json_hash,
        ai_response_json=analysis,
        summary=analysis.get("summary"),
        training_recommendation=analysis.get("training_recommendation"),
        risk_level=analysis.get("risk_level"),
        model_name=model_name,
    )

    response_payload: dict[str, Any] = {
        "ran": True,
        "reason": "generated",
        "analysis": analysis,
        "saved_analysis": _serialize_health_ai_analysis(saved_analysis),
    }
    if invalid_selected_date:
        response_payload["warning"] = "selected_date invalida; se uso la fecha de hoy."
    return response_payload


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
