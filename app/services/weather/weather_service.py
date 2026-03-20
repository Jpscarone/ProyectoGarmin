from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.activity_weather import ActivityWeather
from app.db.models.garmin_activity import GarminActivity
from app.services.weather.client import OpenMeteoClient, WeatherClientError


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

    existing = activity.weather
    if existing is None:
        weather = ActivityWeather(**values)
        activity.weather = weather
        db.add(weather)
        db.commit()
        return ActivityWeatherSyncResult(
            activity_id=activity.id,
            created=True,
            updated=False,
            message="Se guardo el clima historico para esta actividad.",
        )

    changed = _merge_weather_values(existing, values)
    db.commit()
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
