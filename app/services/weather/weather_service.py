from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.activity_weather import ActivityWeather
from app.db.models.garmin_activity import GarminActivity
from app.services.weather.client import OpenMeteoClient, WeatherClientError


logger = logging.getLogger(__name__)


class ActivityWeatherSyncError(Exception):
    """Raised when weather sync cannot complete for an activity."""


@dataclass
class ActivityWeatherSyncResult:
    activity_id: int
    created: bool
    updated: bool
    message: str


@dataclass
class BatchWeatherSyncResult:
    processed: int
    created: int
    updated: int
    skipped: int
    errors: list[str]


def sync_weather_for_activity(db: Session, activity: GarminActivity) -> ActivityWeatherSyncResult:
    existing = activity.weather
    if existing is not None and existing.weather_source == "garmin_activity":
        return ActivityWeatherSyncResult(
            activity_id=activity.id,
            created=False,
            updated=False,
            message="La actividad ya tiene clima nativo de Garmin. Open-Meteo queda como respaldo manual.",
        )

    validation_error = _validate_activity_weather_inputs(activity)
    if validation_error:
        raise ActivityWeatherSyncError(validation_error)

    start_time = activity.start_time
    assert start_time is not None
    end_time = activity.end_time or (
        start_time + timedelta(seconds=activity.duration_sec or 0)
        if activity.duration_sec
        else None
    )
    if end_time is None or end_time <= start_time:
        raise ActivityWeatherSyncError("The activity does not have a valid end time or duration to calculate weather.")

    client = OpenMeteoClient()
    payload = client.fetch_hourly_history(
        latitude=float(activity.start_lat),
        longitude=float(activity.start_lon),
        start_date=start_time.date(),
        end_date=end_time.date(),
    )
    values = _build_activity_weather_values(activity, payload, client.provider_name)
    if existing is None:
        weather = ActivityWeather(**values)
        activity.weather = weather
        db.add(weather)
        db.commit()
        logger.info("Weather synced from Open-Meteo")
        return ActivityWeatherSyncResult(
            activity_id=activity.id,
            created=True,
            updated=False,
            message="Se guardo el clima historico para esta actividad.",
        )

    changed = _merge_weather_values(existing, values)
    db.commit()
    logger.info("Weather synced from Open-Meteo")
    return ActivityWeatherSyncResult(
        activity_id=activity.id,
        created=False,
        updated=changed,
        message="Se actualizo el clima historico para esta actividad." if changed else "La actividad ya tenia clima historico disponible.",
    )


def sync_weather_for_recent_activities(
    db: Session,
    *,
    limit: int = 20,
    only_missing: bool = True,
) -> BatchWeatherSyncResult:
    statement = select(GarminActivity).order_by(GarminActivity.start_time.desc(), GarminActivity.id.desc()).limit(limit)
    activities = list(db.scalars(statement).all())

    processed = 0
    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    for activity in activities:
        if only_missing and activity.weather is not None:
            skipped += 1
            continue
        try:
            result = sync_weather_for_activity(db, activity)
            processed += 1
            if result.created:
                created += 1
            elif result.updated:
                updated += 1
            else:
                skipped += 1
        except ActivityWeatherSyncError as exc:
            skipped += 1
            errors.append(f"Actividad {activity.id}: {exc}")
        except Exception as exc:
            skipped += 1
            errors.append(f"Actividad {activity.id}: {exc}")

    return BatchWeatherSyncResult(
        processed=processed,
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )


def _validate_activity_weather_inputs(activity: GarminActivity) -> str | None:
    if activity.start_lat is None or activity.start_lon is None:
        return "La actividad no tiene latitud/longitud inicial, por eso no se puede consultar el clima."
    if activity.start_time is None:
        return "La actividad no tiene hora de inicio, por eso no se puede consultar el clima."
    if activity.end_time is None and not activity.duration_sec:
        return "La actividad no tiene hora de fin ni duracion, por eso no se puede consultar el clima."
    return None


def _build_activity_weather_values(
    activity: GarminActivity,
    payload: dict[str, Any],
    provider_name: str,
) -> dict[str, Any]:
    hourly = payload.get("hourly", {})
    points = _build_hourly_points(hourly)
    start_time = activity.start_time
    assert start_time is not None
    end_time = activity.end_time or (
        start_time + timedelta(seconds=activity.duration_sec or 0)
        if activity.duration_sec
        else start_time
    )

    start_snapshot = _pick_start_snapshot(points, start_time)
    window_points = _points_during_activity(points, start_time, end_time)
    if not window_points and start_snapshot is not None:
        window_points = [start_snapshot]

    return {
        "garmin_activity_id": activity.id,
        "provider_name": provider_name,
        "weather_source": "open_meteo",
        "synced_at": datetime.now(timezone.utc),
        "condition_summary": "Open-Meteo estimado",
        "temperature_start_c": _numeric_value(start_snapshot, "temperature_2m"),
        "apparent_temperature_start_c": _numeric_value(start_snapshot, "apparent_temperature"),
        "humidity_start_pct": _numeric_value(start_snapshot, "relative_humidity_2m"),
        "dew_point_start_c": _numeric_value(start_snapshot, "dew_point_2m"),
        "wind_speed_start_kmh": _numeric_value(start_snapshot, "wind_speed_10m"),
        "wind_direction_start_deg": _numeric_value(start_snapshot, "wind_direction_10m"),
        "pressure_start_hpa": _numeric_value(start_snapshot, "surface_pressure"),
        "precipitation_start_mm": _numeric_value(start_snapshot, "precipitation"),
        "temperature_min_c": _series_min(window_points, "temperature_2m"),
        "temperature_max_c": _series_max(window_points, "temperature_2m"),
        "wind_speed_avg_kmh": _series_avg(window_points, "wind_speed_10m"),
        "precipitation_total_mm": _series_sum(window_points, "precipitation"),
        "raw_weather_json": json.dumps(payload, ensure_ascii=True, default=str),
    }


def extract_weather_from_garmin_activity(raw_activity_json: str | dict[str, Any] | None) -> dict[str, Any] | None:
    payload = _parse_raw_activity_payload(raw_activity_json)
    if not payload:
        return None

    candidate_values: dict[str, Any] = {
        "temperature_c": _extract_first_numeric(payload, ("temperature", "avgTemperature", "averageTemperature"), min_value=-30, max_value=60),
        "apparent_temperature_c": _extract_first_numeric(payload, ("apparentTemperature", "feelsLikeTemperature"), min_value=-30, max_value=60),
        "humidity_pct": _extract_first_numeric(payload, ("humidity", "relativeHumidity", "humidityPct"), min_value=0, max_value=100),
        "wind_speed_kmh": _extract_first_numeric(payload, ("windSpeed", "windSpeedKmh", "wind_speed_10m"), min_value=0, max_value=200),
        "wind_direction": _extract_first_numeric(payload, ("windDirection", "windDirectionDeg", "wind_direction_10m"), min_value=0, max_value=360),
        "pressure_hpa": _extract_first_numeric(payload, ("pressure", "surfacePressure", "pressureHpa"), min_value=800, max_value=1100),
        "precipitation_mm": _extract_first_numeric(payload, ("precipitation", "precipitationMm", "rain"), min_value=0, max_value=500),
        "condition": _extract_first_text(payload, ("weatherType", "condition", "weather", "weatherCondition")),
    }

    if not any(value is not None for value in candidate_values.values()):
        return None

    candidate_values["source"] = "garmin_activity"
    return candidate_values


def _build_hourly_points(hourly: dict[str, Any]) -> list[dict[str, Any]]:
    times = hourly.get("time")
    if not isinstance(times, list):
        raise ActivityWeatherSyncError("Weather provider returned hourly data without timestamps.")

    field_names = [
        "temperature_2m",
        "apparent_temperature",
        "relative_humidity_2m",
        "dew_point_2m",
        "wind_speed_10m",
        "wind_direction_10m",
        "surface_pressure",
        "precipitation",
    ]

    points: list[dict[str, Any]] = []
    for index, timestamp_text in enumerate(times):
        if not isinstance(timestamp_text, str):
            continue
        try:
            timestamp = datetime.fromisoformat(timestamp_text)
        except ValueError:
            continue

        point: dict[str, Any] = {"time": timestamp}
        for field_name in field_names:
            values = hourly.get(field_name)
            if isinstance(values, list) and index < len(values):
                point[field_name] = values[index]
        points.append(point)

    if not points:
        raise ActivityWeatherSyncError("Weather provider returned hourly data, but no usable timestamps were parsed.")
    return points


def _pick_start_snapshot(points: list[dict[str, Any]], start_time: datetime) -> dict[str, Any] | None:
    return min(points, key=lambda point: abs((point["time"] - start_time).total_seconds()), default=None)


def _points_during_activity(
    points: list[dict[str, Any]],
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    return [
        point
        for point in points
        if start_time <= point["time"] <= end_time
    ]


def _numeric_value(point: dict[str, Any] | None, field_name: str) -> float | None:
    if not point:
        return None
    value = point.get(field_name)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _series_values(points: list[dict[str, Any]], field_name: str) -> list[float]:
    values: list[float] = []
    for point in points:
        numeric = _numeric_value(point, field_name)
        if numeric is not None:
            values.append(numeric)
    return values


def _series_min(points: list[dict[str, Any]], field_name: str) -> float | None:
    values = _series_values(points, field_name)
    return min(values) if values else None


def _series_max(points: list[dict[str, Any]], field_name: str) -> float | None:
    values = _series_values(points, field_name)
    return max(values) if values else None


def _series_avg(points: list[dict[str, Any]], field_name: str) -> float | None:
    values = _series_values(points, field_name)
    return round(mean(values), 2) if values else None


def _series_sum(points: list[dict[str, Any]], field_name: str) -> float | None:
    values = _series_values(points, field_name)
    return round(sum(values), 2) if values else None


def _merge_weather_values(weather: ActivityWeather, incoming: dict[str, Any]) -> bool:
    changed = False
    for field, value in incoming.items():
        if field == "garmin_activity_id":
            continue
        current = getattr(weather, field)
        if value is None:
            continue
        if current != value:
            setattr(weather, field, value)
            changed = True
    return changed


def upsert_weather_from_garmin_activity(
    db: Session,
    activity: GarminActivity,
    raw_activity_json: str | dict[str, Any] | None,
) -> ActivityWeather | None:
    extracted = extract_weather_from_garmin_activity(raw_activity_json)
    if extracted is None:
        logger.info("No Garmin weather found; Open-Meteo manual sync available")
        return activity.weather

    values = {
        "garmin_activity_id": activity.id,
        "provider_name": "Garmin Activity",
        "weather_source": "garmin_activity",
        "synced_at": datetime.now(timezone.utc),
        "condition_summary": extracted.get("condition"),
        "temperature_start_c": extracted.get("temperature_c"),
        "apparent_temperature_start_c": extracted.get("apparent_temperature_c"),
        "humidity_start_pct": extracted.get("humidity_pct"),
        "wind_speed_start_kmh": extracted.get("wind_speed_kmh"),
        "wind_speed_avg_kmh": extracted.get("wind_speed_kmh"),
        "wind_direction_start_deg": extracted.get("wind_direction"),
        "pressure_start_hpa": extracted.get("pressure_hpa"),
        "precipitation_start_mm": extracted.get("precipitation_mm"),
        "raw_weather_json": json.dumps(extracted, ensure_ascii=True, default=str),
    }

    existing = activity.weather
    if existing is None:
        weather = ActivityWeather(**values)
        activity.weather = weather
        db.add(weather)
        db.flush()
        logger.info("Weather extracted from Garmin activity")
        return weather

    changed = _merge_weather_values(existing, values)
    if changed:
        db.flush()
    logger.info("Weather extracted from Garmin activity")
    return existing


def _parse_raw_activity_payload(raw_activity_json: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if raw_activity_json is None:
        return None
    if isinstance(raw_activity_json, dict):
        return raw_activity_json
    if not isinstance(raw_activity_json, str) or not raw_activity_json.strip():
        return None
    try:
        parsed = json.loads(raw_activity_json)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_first_numeric(
    payload: dict[str, Any],
    keys: tuple[str, ...],
    *,
    min_value: float,
    max_value: float,
) -> float | None:
    for value in _iter_payload_values(payload):
        if not isinstance(value, dict):
            continue
        for key in keys:
            if key not in value:
                continue
            numeric = _safe_float(value.get(key))
            if numeric is None:
                continue
            if min_value <= numeric <= max_value:
                return numeric
    return None


def _extract_first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for value in _iter_payload_values(payload):
        if not isinstance(value, dict):
            continue
        for key in keys:
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
            if isinstance(text, dict):
                nested = next((item for item in text.values() if isinstance(item, str) and item.strip()), None)
                if nested:
                    return nested.strip()
    return None


def _iter_payload_values(payload: Any):
    stack = [payload]
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
