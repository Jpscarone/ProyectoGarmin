from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.services.garmin.auth import GarminServiceError, get_garmin_auth_context
from app.services.garmin.client import GarminClient


logger = logging.getLogger(__name__)


@dataclass
class GarminHealthSyncResult:
    athlete_name: str
    days_reviewed: int
    created: int
    updated: int
    errors: list[str]


def sync_recent_health(
    db: Session,
    settings: Settings,
    days: int = 7,
    mfa_code: str | None = None,
    athlete_id: int | None = None,
) -> GarminHealthSyncResult:
    athlete = _get_sync_athlete(db, athlete_id=athlete_id)
    auth_context = get_garmin_auth_context(settings, mfa_code=mfa_code)
    client = GarminClient(auth_context.client)

    metric_dates = [date.today() - timedelta(days=offset) for offset in range(max(days, 1))]
    existing_by_date = {
        metric.metric_date: metric
        for metric in db.scalars(
            select(DailyHealthMetric).where(DailyHealthMetric.athlete_id == athlete.id)
        )
    }

    created = 0
    updated = 0
    errors: list[str] = []

    for metric_date in metric_dates:
        try:
            payloads = client.get_health_payloads(metric_date)
            values = _build_health_values(athlete.id, metric_date, payloads)
            has_any_metric = any(
                value is not None
                for key, value in values.items()
                if key not in {"athlete_id", "metric_date", "raw_health_json"}
            )
            if not has_any_metric and values["raw_health_json"] is None:
                continue

            existing = existing_by_date.get(metric_date)
            if existing is None:
                db.add(DailyHealthMetric(**values))
                created += 1
            else:
                if _merge_metric_values(existing, values):
                    updated += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Garmin health sync failed for %s", metric_date)
            errors.append(f"{metric_date.isoformat()}: {exc}")

    return GarminHealthSyncResult(
        athlete_name=athlete.name,
        days_reviewed=len(metric_dates),
        created=created,
        updated=updated,
        errors=errors,
    )


def _get_sync_athlete(db: Session, athlete_id: int | None = None) -> Athlete:
    if athlete_id is not None:
        athlete = db.get(Athlete, athlete_id)
        if athlete is None:
            raise GarminServiceError("Selected athlete was not found for Garmin health sync.")
        return athlete
    athlete = db.scalar(select(Athlete).order_by(Athlete.created_at.asc(), Athlete.id.asc()))
    if athlete is None:
        raise GarminServiceError("Create at least one athlete before syncing Garmin health metrics.")
    return athlete


def _build_health_values(
    athlete_id: int,
    metric_date: date,
    payloads: dict[str, object],
) -> dict[str, Any]:
    sleep = _ensure_dict(payloads.get("sleep"))
    daily_sleep = _first_dict(sleep, "dailySleepDTO", "sleepDTO")
    stress = _ensure_dict(payloads.get("stress"))
    body_battery_points = _ensure_list(payloads.get("body_battery"))
    hrv = _ensure_dict(payloads.get("hrv"))
    resting_hr = _ensure_dict(payloads.get("resting_hr"))
    respiration = _ensure_dict(payloads.get("respiration"))
    spo2 = _ensure_dict(payloads.get("spo2"))
    max_metrics = _ensure_dict(payloads.get("max_metrics"))
    daily_summary = _ensure_dict(payloads.get("daily_summary"))
    training_readiness = payloads.get("training_readiness")

    body_battery_values = _extract_numeric_series(
        body_battery_points,
        value_keys=("bodyBatteryValue", "bodyBattery", "value"),
    )
    if not body_battery_values:
        body_battery_values = _extract_body_battery_levels(body_battery_points)

    sleep_seconds = _to_float(
        _first_nested(
            daily_sleep,
            sleep,
            daily_summary,
            keys=("sleepTimeSeconds", "sleepTime", "totalSleepSeconds", "overallSleepSeconds"),
        )
    )
    hrv_summary = _first_dict(hrv, "hrvSummary", "lastNightAvg", "hrvReadings", "summary")
    max_metric_values = _ensure_list(max_metrics.get("metricValues"))
    recovery_metrics = _ensure_list(_find_first_list(training_readiness, ("metrics", "recoveryMetrics")))

    raw_payload = {
        key: value
        for key, value in payloads.items()
        if value not in (None, {}, [])
    }

    return {
        "athlete_id": athlete_id,
        "metric_date": metric_date,
        "sleep_duration_minutes": _seconds_to_minutes(sleep_seconds),
        "sleep_hours": round(sleep_seconds / 3600, 2) if sleep_seconds is not None else None,
        "sleep_score": _to_int(
            _first_nested(
                daily_sleep,
                sleep,
                keys=("sleepScore", "overallSleepScore", "overallScore"),
            )
        ) or _to_int(
            _first_nested(
                _first_dict(_first_dict(daily_sleep, "sleepScores"), "overall"),
                keys=("value",),
            )
        ),
        "deep_sleep_min": _seconds_to_minutes(
            _first_nested(daily_sleep, sleep, keys=("deepSleepSeconds", "deepSleepDurationInSeconds"))
        ),
        "rem_sleep_min": _seconds_to_minutes(
            _first_nested(daily_sleep, sleep, keys=("remSleepSeconds", "remSleepDurationInSeconds"))
        ),
        "awake_count": _to_int(
            _first_nested(daily_sleep, sleep, keys=("awakeCount", "awakePeriods"))
        ),
        "stress_avg": _to_int(
            _first_nested(
                stress,
                daily_summary,
                keys=("averageStressLevel", "avgStressLevel", "overallStressLevel"),
            )
        ),
        "stress_max": _to_int(
            _first_nested(stress, daily_summary, keys=("maxStressLevel", "highestStressLevel"))
        ),
        "high_stress_duration_min": _seconds_to_minutes(
            _first_nested(stress, keys=("highStressDuration", "highStressDurationInSeconds"))
        ) or _minutes_value(_first_nested(stress, keys=("highStressDurationInMinutes",))),
        "body_battery_morning": _to_int(body_battery_values[0]) if body_battery_values else None,
        "body_battery_start": _to_int(body_battery_values[0]) if body_battery_values else None,
        "body_battery_min": min(body_battery_values) if body_battery_values else None,
        "body_battery_max": max(body_battery_values) if body_battery_values else None,
        "body_battery_end": _to_int(body_battery_values[-1]) if body_battery_values else None,
        "hrv_status": _to_str(
            _first_nested(hrv, hrv_summary, keys=("status", "hrvStatus", "weeklyStatus"))
        ),
        "hrv_value": _to_float(
            _first_nested(hrv, hrv_summary, keys=("lastNightAvg", "average", "avg", "value"))
        ),
        "hrv_avg_ms": _to_float(
            _first_nested(hrv, hrv_summary, keys=("lastNightAvg", "average", "avg", "value"))
        ),
        "resting_hr": _to_int(
            _first_nested(
                resting_hr,
                daily_summary,
                keys=("allMetrics", "restingHeartRate", "restingHeartRateValue", "restingHR"),
            )
        ) or _extract_metric_id_value(resting_hr, metric_id=60),
        "avg_daily_hr": _to_int(
            _first_nested(daily_summary, keys=("averageHeartRate", "avgHeartRate", "averageHR"))
        ),
        "training_load": _extract_training_load(training_readiness, daily_summary),
        "recovery_time_hours": _extract_recovery_time_hours(training_readiness, recovery_metrics),
        "vo2max": _extract_vo2max(max_metrics, max_metric_values),
        "spo2_avg": _to_float(
            _first_nested(spo2, keys=("averageValue", "averageSpO2", "avgSpo2"))
        ),
        "respiration_avg": _to_float(
            _first_nested(respiration, keys=("avgWakingRespirationValue", "averageRespirationValue", "respirationAvg"))
        ),
        "notes": None,
        "source": "garmin",
        "raw_health_json": json.dumps(raw_payload, ensure_ascii=True, default=str) if raw_payload else None,
    }


def _merge_metric_values(metric: DailyHealthMetric, incoming: dict[str, Any]) -> bool:
    changed = False
    for field, value in incoming.items():
        if field in {"athlete_id", "metric_date"}:
            continue
        current = getattr(metric, field)
        if value is None:
            continue
        if current != value:
            setattr(metric, field, value)
            changed = True
    return changed


def _ensure_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ensure_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_dict(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _find_first_list(source: object, keys: tuple[str, ...]) -> list[Any] | None:
    if isinstance(source, dict):
        for key in keys:
            value = source.get(key)
            if isinstance(value, list):
                return value
    if isinstance(source, list):
        for item in source:
            found = _find_first_list(item, keys)
            if found:
                return found
    return None


def _first_nested(*sources: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]
    return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _seconds_to_minutes(value: Any) -> int | None:
    seconds = _to_float(value)
    if seconds is None:
        return None
    return int(round(seconds / 60))


def _minutes_value(value: Any) -> int | None:
    minutes = _to_float(value)
    if minutes is None:
        return None
    return int(round(minutes))


def _extract_numeric_series(items: list[Any], *, value_keys: tuple[str, ...]) -> list[int]:
    values: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in value_keys:
            numeric = _to_int(item.get(key))
            if numeric is not None:
                values.append(numeric)
                break
    return values


def _extract_body_battery_levels(items: list[Any]) -> list[int]:
    values: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        points = item.get("bodyBatteryValuesArray")
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            numeric = _to_int(point[1])
            if numeric is not None:
                values.append(numeric)
    return values


def _extract_metric_id_value(source: dict[str, Any], metric_id: int) -> int | None:
    metrics = source.get("allMetrics")
    if not isinstance(metrics, list):
        return None
    for item in metrics:
        if not isinstance(item, dict):
            continue
        if _to_int(item.get("metricId")) != metric_id:
            continue
        return _to_int(_first_nested(item, keys=("value", "metricValue")))
    return None


def _extract_recovery_time_hours(training_readiness: object, recovery_metrics: list[Any]) -> float | None:
    candidate = None
    if isinstance(training_readiness, dict):
        candidate = _first_nested(
            training_readiness,
            keys=("recoveryTime", "recoveryTimeHours", "remainingRecoveryTime", "recoveryHours"),
        )
    elif isinstance(training_readiness, list):
        for item in training_readiness:
            if not isinstance(item, dict):
                continue
            candidate = _first_nested(
                item,
                keys=("recoveryTime", "recoveryTimeHours", "remainingRecoveryTime", "recoveryHours"),
            )
            if candidate is not None:
                break

    if candidate is None:
        for item in recovery_metrics:
            if not isinstance(item, dict):
                continue
            candidate = _first_nested(item, keys=("value", "metricValue", "recoveryTime"))
            if candidate is not None:
                break

    numeric = _to_float(candidate)
    if numeric is None:
        return None
    if numeric > 200:
        return round(numeric / 3600, 2)
    return round(numeric, 2)


def _extract_vo2max(max_metrics: dict[str, Any], metric_values: list[Any]) -> float | None:
    for item in metric_values:
        if not isinstance(item, dict):
            continue
        key = _to_str(_first_nested(item, keys=("metricType", "metricName", "type", "key")))
        if key and "VO2" in key.upper():
            value = _to_float(_first_nested(item, keys=("value", "metricValue", "maxMetricValue")))
            if value is not None:
                return value
    return _to_float(
        _first_nested(
            max_metrics,
            keys=("vo2MaxPreciseValue", "vo2MaxValue", "cyclingVo2Max", "runningVo2Max"),
        )
    )


def _extract_training_load(training_readiness: object, daily_summary: dict[str, Any]) -> float | None:
    if isinstance(training_readiness, dict):
        value = _to_float(
            _first_nested(
                training_readiness,
                keys=("trainingLoad", "acuteLoad", "load", "exerciseLoad"),
            )
        )
        if value is not None:
            return value

    if isinstance(training_readiness, list):
        for item in training_readiness:
            if not isinstance(item, dict):
                continue
            value = _to_float(
                _first_nested(
                    item,
                    keys=("trainingLoad", "acuteLoad", "load", "exerciseLoad"),
                )
            )
            if value is not None:
                return value

    return _to_float(
        _first_nested(
            daily_summary,
            keys=("trainingLoad", "acuteTrainingLoad", "load"),
        )
    )
