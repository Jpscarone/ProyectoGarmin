from __future__ import annotations

from datetime import date, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.garmin_activity import GarminActivity
from app.db.models.goal import Goal
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.schemas.daily_health_metric import HealthReadinessEvaluation, HealthReadinessSummary
from app.services.daily_health_metric_service import list_health_metrics_for_athlete_range

HRV_TREND_UP_THRESHOLD_PCT = 8.0
HRV_TREND_DOWN_THRESHOLD_PCT = -8.0
READINESS_LIMITER_PRIORITY = {
    "hrv": 0,
    "resting_hr": 1,
    "sleep": 2,
    "body_battery": 3,
    "stress": 4,
}


def build_health_readiness_summary(
    db: Session,
    athlete_id: int,
    reference_date: date,
) -> HealthReadinessSummary:
    start_date = reference_date - timedelta(days=13)
    metrics = list_health_metrics_for_athlete_range(db, athlete_id, start_date, reference_date)

    sleep_7d = _average_window(metrics, reference_date, 7, _sleep_minutes_value)
    sleep_14d = _average_window(metrics, reference_date, 14, _sleep_minutes_value)
    resting_hr_14d = _average_window(metrics, reference_date, 14, lambda item: item.resting_hr)
    resting_hr_3d = _average_window(metrics, reference_date, 3, lambda item: item.resting_hr)
    hrv_14d = _average_window(metrics, reference_date, 14, lambda item: item.hrv_value or item.hrv_avg_ms)
    hrv_7d = _average_window(metrics, reference_date, 7, lambda item: item.hrv_value or item.hrv_avg_ms)
    stress_3d = _average_window(metrics, reference_date, 3, lambda item: item.stress_avg)
    stress_7d = _average_window(metrics, reference_date, 7, lambda item: item.stress_avg)
    body_battery_morning_3d = _average_window(metrics, reference_date, 3, lambda item: item.body_battery_morning or item.body_battery_start)
    body_battery_morning_7d = _average_window(metrics, reference_date, 7, lambda item: item.body_battery_morning or item.body_battery_start)

    available_days_14d = len({item.metric_date for item in metrics})
    missing_days_14d = max(0, 14 - available_days_14d)

    return HealthReadinessSummary(
        athlete_id=athlete_id,
        reference_date=reference_date,
        sleep_avg_7d=_minutes_to_hours(sleep_7d),
        sleep_avg_14d=_minutes_to_hours(sleep_14d),
        resting_hr_avg_14d=resting_hr_14d,
        resting_hr_avg_3d=resting_hr_3d,
        resting_hr_delta_3d_vs_14d=_delta(resting_hr_3d, resting_hr_14d),
        hrv_avg_14d=hrv_14d,
        hrv_avg_7d=hrv_7d,
        hrv_trend=_hrv_trend(hrv_7d, hrv_14d),
        stress_avg_3d=stress_3d,
        stress_avg_7d=stress_7d,
        body_battery_morning_avg_3d=body_battery_morning_3d,
        body_battery_morning_avg_7d=body_battery_morning_7d,
        available_days_14d=available_days_14d,
        missing_days_14d=missing_days_14d,
    )


def evaluate_health_readiness(summary: HealthReadinessSummary) -> HealthReadinessEvaluation:
    data_quality_reasons: list[str] = []
    if summary.available_days_14d < 5:
        data_quality_reasons.append("Hay menos de 5 dias con datos en la ventana de 14 dias.")
        return HealthReadinessEvaluation(
            readiness_score=None,
            readiness_status="insufficient_data",
            readiness_label="sin datos suficientes",
            main_limiter=None,
            reasons=[],
            recommendation="Todavia no hay datos suficientes para evaluar la tendencia.",
            data_quality="poor",
            data_quality_reasons=data_quality_reasons,
        )

    penalties: list[dict[str, object]] = []
    reasons: list[str] = []

    if summary.sleep_avg_7d is not None:
        if summary.sleep_avg_7d < 6.0:
            penalties.append({"limiter": "sleep", "points": 15, "reason": "Sueno promedio bajo en los ultimos 7 dias."})
        elif summary.sleep_avg_7d < 6.75:
            penalties.append({"limiter": "sleep", "points": 8, "reason": "Sueno algo corto en los ultimos 7 dias."})

    if summary.resting_hr_delta_3d_vs_14d is not None:
        if summary.resting_hr_delta_3d_vs_14d >= 6.0:
            penalties.append({"limiter": "resting_hr", "points": 18, "reason": "La frecuencia cardiaca en reposo subio claramente en los ultimos 3 dias."})
        elif summary.resting_hr_delta_3d_vs_14d >= 3.0:
            penalties.append({"limiter": "resting_hr", "points": 10, "reason": "La frecuencia cardiaca en reposo esta algo mas alta en los ultimos 3 dias."})

    if summary.hrv_trend == "down":
        penalties.append({"limiter": "hrv", "points": 18, "reason": "La HRV viene en descenso frente a la referencia de 14 dias."})

    if summary.stress_avg_3d is not None:
        if summary.stress_avg_3d >= 60:
            penalties.append({"limiter": "stress", "points": 15, "reason": "El estres promedio de los ultimos 3 dias es alto."})
        elif summary.stress_avg_3d >= 45:
            penalties.append({"limiter": "stress", "points": 8, "reason": "El estres promedio reciente esta moderadamente elevado."})

    if summary.body_battery_morning_avg_3d is not None:
        if summary.body_battery_morning_avg_3d < 35:
            penalties.append({"limiter": "body_battery", "points": 18, "reason": "El body battery matinal reciente esta bajo."})
        elif summary.body_battery_morning_avg_3d < 50:
            penalties.append({"limiter": "body_battery", "points": 10, "reason": "El body battery matinal reciente esta algo comprometido."})

    total_penalty = sum(int(item["points"]) for item in penalties)
    score = max(0, 100 - total_penalty)

    for item in penalties:
        reasons.append(str(item["reason"]))

    main_limiter = _select_main_limiter(penalties)
    readiness_status, readiness_label = _readiness_status(score)

    if summary.available_days_14d < 10:
        data_quality_reasons.append("La ventana de 14 dias tiene varios faltantes; conviene leer el score con prudencia.")
    if summary.missing_days_14d == 0:
        data_quality = "good"
    elif summary.available_days_14d >= 10:
        data_quality = "fair"
    else:
        data_quality = "poor"

    return HealthReadinessEvaluation(
        readiness_score=score,
        readiness_status=readiness_status,
        readiness_label=readiness_label,
        main_limiter=main_limiter,
        reasons=reasons,
        recommendation=_readiness_recommendation(readiness_status),
        data_quality=data_quality,
        data_quality_reasons=data_quality_reasons,
    )


def build_health_training_context(
    db: Session,
    athlete_id: int,
    reference_date: date,
) -> dict:
    start_date = reference_date - timedelta(days=6)
    end_date = reference_date

    planned_sessions = _list_planned_sessions_for_range(db, athlete_id, start_date, end_date)
    activities = _list_activities_for_range(db, athlete_id, start_date, end_date)
    hard_session_dates: list[date] = []

    hard_session_dates.extend(
        session.training_day.day_date
        for session in planned_sessions
        if session.training_day is not None and _is_hard_planned_session(session)
    )
    hard_session_dates.extend(
        activity.start_time.date()
        for activity in activities
        if activity.start_time is not None and _is_hard_activity(activity)
    )

    last_activity_date = max((activity.start_time.date() for activity in activities if activity.start_time), default=None)
    last_hard_session_date = max(hard_session_dates, default=None)
    next_goal = _next_goal_within_days(db, athlete_id, reference_date, days=7)

    return {
        "planned_sessions_last_7d": len(planned_sessions),
        "completed_activities_last_7d": len(activities),
        "hard_sessions_last_7d": len(set(hard_session_dates)),
        "last_activity_date": last_activity_date.isoformat() if last_activity_date else None,
        "last_hard_session_date": last_hard_session_date.isoformat() if last_hard_session_date else None,
        "days_since_last_hard_session": (reference_date - last_hard_session_date).days if last_hard_session_date else None,
        "total_duration_minutes_last_7d": _total_activity_duration_minutes(activities),
        "total_distance_km_last_7d": _total_activity_distance_km(activities),
        "race_week": next_goal is not None,
        "next_goal_name": getattr(next_goal, "name", None) if next_goal else None,
        "days_to_next_goal": (next_goal.event_date - reference_date).days if next_goal and next_goal.event_date else None,
    }


def build_health_llm_json(
    athlete,
    summary: HealthReadinessSummary,
    evaluation: HealthReadinessEvaluation,
    reference_date: date,
    training_context: dict | None = None,
) -> dict:
    return {
        "schema_version": "health_readiness_v1",
        "reference_date": reference_date.isoformat(),
        "athlete": {
            "id": getattr(athlete, "id", None),
            "name": getattr(athlete, "name", None),
            "main_goal": _athlete_main_goal(athlete),
        },
        "period": {
            "days": 14,
            "focus_days": 7,
            "acute_days": 3,
        },
        "data_quality": {
            "level": evaluation.data_quality,
            "available_days_14d": summary.available_days_14d,
            "missing_days_14d": summary.missing_days_14d,
            "reasons": evaluation.data_quality_reasons,
        },
        "readiness_local": {
            "readiness_score": evaluation.readiness_score,
            "readiness_status": evaluation.readiness_status,
            "readiness_label": evaluation.readiness_label,
            "main_limiter": evaluation.main_limiter,
            "reasons": evaluation.reasons,
            "recommendation": evaluation.recommendation,
        },
        "health_summary": summary.model_dump(),
        "training_context": training_context or {},
    }


def _list_planned_sessions_for_range(
    db: Session,
    athlete_id: int,
    date_from: date,
    date_to: date,
) -> list[PlannedSession]:
    statement = (
        select(PlannedSession)
        .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
        .where(
            PlannedSession.athlete_id == athlete_id,
            TrainingDay.day_date >= date_from,
            TrainingDay.day_date <= date_to,
        )
        .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc(), PlannedSession.id.asc())
    )
    return list(db.scalars(statement).all())


def _list_activities_for_range(
    db: Session,
    athlete_id: int,
    date_from: date,
    date_to: date,
) -> list[GarminActivity]:
    activities = list(
        db.scalars(
            select(GarminActivity)
            .where(GarminActivity.athlete_id == athlete_id)
            .order_by(GarminActivity.start_time.asc(), GarminActivity.id.asc())
        ).all()
    )
    return [
        activity
        for activity in activities
        if activity.start_time is not None and date_from <= activity.start_time.date() <= date_to
    ]


def _is_hard_planned_session(session: PlannedSession) -> bool:
    if bool(getattr(session, "is_key_session", False)):
        return True

    text_parts = [
        getattr(session, "session_type", None),
        getattr(session, "target_notes", None),
        getattr(session, "description_text", None),
        getattr(session, "name", None),
        getattr(session, "target_hr_zone", None),
        getattr(session, "target_pace_zone", None),
        getattr(session, "target_power_zone", None),
    ]
    text = " ".join(str(part).lower() for part in text_parts if part)
    hard_terms = ("z4", "z5", "interval", "series", "tempo", "threshold", "umbral", "vo2", "intenso")
    return any(term in text for term in hard_terms)


def _is_hard_activity(activity: GarminActivity) -> bool:
    if activity.training_effect_anaerobic is not None and activity.training_effect_anaerobic >= 2.5:
        return True
    if activity.training_effect_aerobic is not None and activity.training_effect_aerobic >= 3.5:
        return True
    if activity.training_load is not None and activity.training_load >= 150:
        return True
    if activity.avg_hr is not None and activity.max_hr is not None and activity.max_hr > 0:
        return (activity.avg_hr / activity.max_hr) >= 0.82
    return False


def _next_goal_within_days(db: Session, athlete_id: int, reference_date: date, days: int) -> Goal | None:
    end_date = reference_date + timedelta(days=days)
    statement = (
        select(Goal)
        .where(
            Goal.athlete_id == athlete_id,
            Goal.event_date.is_not(None),
            Goal.event_date >= reference_date,
            Goal.event_date <= end_date,
        )
        .order_by(Goal.event_date.asc(), Goal.id.asc())
    )
    return db.scalar(statement)


def _total_activity_duration_minutes(activities: list[GarminActivity]) -> float:
    total_seconds = sum(float(activity.duration_sec or activity.moving_duration_sec or 0) for activity in activities)
    return round(total_seconds / 60.0, 1)


def _total_activity_distance_km(activities: list[GarminActivity]) -> float:
    total_meters = sum(float(activity.distance_m or 0) for activity in activities)
    return round(total_meters / 1000.0, 2)


def _average_window(metrics, reference_date: date, days: int, value_getter) -> float | None:
    start_date = reference_date - timedelta(days=days - 1)
    values: list[float] = []
    for item in metrics:
        if not (start_date <= item.metric_date <= reference_date):
            continue
        value = value_getter(item)
        if value is None:
            continue
        values.append(float(value))
    if not values:
        return None
    return round(mean(values), 2)


def _minutes_to_hours(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 60.0, 2)


def _sleep_minutes_value(item) -> float | None:
    if item.sleep_duration_minutes is not None:
        return float(item.sleep_duration_minutes)
    if item.sleep_hours is not None:
        return float(item.sleep_hours) * 60.0
    return None


def _delta(recent: float | None, baseline: float | None) -> float | None:
    if recent is None or baseline is None:
        return None
    return round(recent - baseline, 2)


def _hrv_trend(hrv_avg_7d: float | None, hrv_avg_14d: float | None) -> str | None:
    if hrv_avg_7d is None or hrv_avg_14d in (None, 0):
        return "insufficient_data"
    delta_pct = ((hrv_avg_7d - hrv_avg_14d) / hrv_avg_14d) * 100.0
    if delta_pct <= HRV_TREND_DOWN_THRESHOLD_PCT:
        return "down"
    if delta_pct >= HRV_TREND_UP_THRESHOLD_PCT:
        return "up"
    return "stable"


def _select_main_limiter(penalties: list[dict[str, object]]) -> str | None:
    if not penalties:
        return None
    sorted_penalties = sorted(
        penalties,
        key=lambda item: (
            -int(item["points"]),
            READINESS_LIMITER_PRIORITY.get(str(item["limiter"]), 99),
        ),
    )
    return str(sorted_penalties[0]["limiter"])


def _readiness_status(score: int) -> tuple[str, str]:
    if score >= 80:
        return "green", "entrenar normal"
    if score >= 65:
        return "yellow", "controlar intensidad"
    if score >= 50:
        return "orange", "solo suave"
    return "red", "descanso o recuperacion"


def _readiness_recommendation(status: str) -> str:
    if status == "green":
        return "Podes entrenar segun lo planificado."
    if status == "yellow":
        return "Podes entrenar, pero evita forzar por encima de lo previsto."
    if status == "orange":
        return "Conviene hacer solo trabajo suave, tecnica, movilidad o recuperacion."
    if status == "red":
        return "Conviene descansar o hacer recuperacion muy liviana."
    return "Todavia no hay datos suficientes para evaluar la tendencia."


def _athlete_main_goal(athlete) -> dict | None:
    goals = list(getattr(athlete, "goals", []) or [])
    primary_goal = next((goal for goal in goals if getattr(goal, "goal_role", None) == "primary"), None)
    goal = primary_goal

    if goal is None:
        training_plans = list(getattr(athlete, "training_plans", []) or [])
        active_plan = next((plan for plan in training_plans if getattr(plan, "status", None) == "active" and getattr(plan, "goal", None) is not None), None)
        if active_plan is not None:
            goal = active_plan.goal

    if goal is None:
        return None

    return {
        "id": getattr(goal, "id", None),
        "name": getattr(goal, "name", None),
        "sport_type": getattr(goal, "sport_type", None),
        "event_type": getattr(goal, "event_type", None),
        "event_date": getattr(goal, "event_date", None).isoformat() if getattr(goal, "event_date", None) else None,
        "distance_km": getattr(goal, "distance_km", None),
    }
