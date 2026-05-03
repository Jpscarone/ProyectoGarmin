from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.athlete import Athlete
from app.db.models.garmin_activity import GarminActivity
from app.db.models.garmin_activity_lap import GarminActivityLap
from app.services.garmin.auth import GarminServiceError, get_garmin_auth_context
from app.services.garmin.client import GarminClient
from app.services.weather.weather_service import upsert_weather_from_garmin_activity


logger = logging.getLogger(__name__)


@dataclass
class GarminSyncResult:
    athlete_name: str
    found: int
    inserted: int
    existing: int
    errors: list[str]


def sync_recent_activities(
    db: Session,
    settings: Settings,
    limit: int = 20,
    mfa_code: str | None = None,
    athlete_id: int | None = None,
) -> GarminSyncResult:
    recent_days_start = date.today() - timedelta(days=30)
    return sync_activities_by_date(
        db,
        settings,
        start_date=recent_days_start,
        end_date=date.today(),
        mfa_code=mfa_code,
        athlete_id=athlete_id,
        limit=limit,
    )


def sync_activities_by_date(
    db: Session,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    mfa_code: str | None = None,
    athlete_id: int | None = None,
    limit: int | None = None,
) -> GarminSyncResult:
    athlete = _get_sync_athlete(db, athlete_id=athlete_id)
    auth_context = get_garmin_auth_context(settings, mfa_code=mfa_code)
    client = GarminClient(auth_context.client)

    if start_date > end_date:
        start_date, end_date = end_date, start_date
    activities_in_range = client.get_activities_by_date(start_date, end_date, sortorder="asc")
    if limit is not None:
        activities_in_range = activities_in_range[: max(limit, 0)]
    found = len(activities_in_range)
    inserted = 0
    existing = 0
    errors: list[str] = []

    existing_by_garmin_id = {
        activity.garmin_activity_id: activity
        for activity in db.scalars(select(GarminActivity).where(GarminActivity.athlete_id == athlete.id))
    }

    for activity_summary in activities_in_range:
        garmin_activity_id = _to_int(_get_first(activity_summary, "activityId", "activity_id"))
        if garmin_activity_id is None:
            errors.append("An activity without activityId was skipped.")
            continue

        try:
            detailed_summary = client.get_activity_summary(garmin_activity_id)
            details = client.get_activity_details(garmin_activity_id)
            splits = client.get_activity_splits(garmin_activity_id)
            debug_payload = {
                "recent_summary": activity_summary,
                "summary": detailed_summary,
                "details": details,
                "splits_preview": splits[:3],
            }

            summary_dto = _extract_summary_dto(detailed_summary, activity_summary)
            metadata_dto = _extract_metadata_dto(detailed_summary, activity_summary)

            activity_values = _build_activity_values(
                athlete_id=athlete.id,
                garmin_activity_id=garmin_activity_id,
                activity_summary=activity_summary,
                detailed_summary=detailed_summary,
                details=details,
                summary_dto=summary_dto,
                metadata_dto=metadata_dto,
                debug_payload=debug_payload,
            )

            activity = existing_by_garmin_id.get(garmin_activity_id)
            if activity is None:
                activity = GarminActivity(**activity_values)
                db.add(activity)
                db.flush()
                inserted += 1
            else:
                existing += 1
                for field, value in activity_values.items():
                    setattr(activity, field, value)
                db.execute(
                    delete(GarminActivityLap).where(GarminActivityLap.garmin_activity_id_fk == activity.id)
                )
                db.flush()

            upsert_weather_from_garmin_activity(db, activity, debug_payload)

            for index, lap in enumerate(splits, start=1):
                lap_summary = _extract_lap_summary(lap)
                avg_speed = _to_float(_get_first(lap_summary, "averageSpeed", "avgSpeed"))
                activity.laps.append(
                    GarminActivityLap(
                        lap_number=_to_int(_get_first(lap, "lapNumber", "splitNumber")) or index,
                        lap_type=_infer_lap_type(lap),
                        start_time=_parse_datetime(_get_first(lap_summary, "startTimeGMT", "startTimeLocal", "startTime")),
                        duration_sec=_to_int(_get_first(lap_summary, "duration", "elapsedDuration")),
                        moving_duration_sec=_to_int(_get_first(lap_summary, "movingDuration")),
                        distance_m=_to_float(_get_first(lap_summary, "distance")),
                        elevation_gain_m=_to_float(_get_first(lap_summary, "elevationGain")),
                        elevation_loss_m=_to_float(_get_first(lap_summary, "elevationLoss")),
                        avg_hr=_to_int(_get_first(lap_summary, "averageHR", "avgHR")),
                        max_hr=_to_int(_get_first(lap_summary, "maxHR")),
                        avg_power=_to_int(_get_first(lap_summary, "averagePower", "avgPower")),
                        max_power=_to_int(_get_first(lap_summary, "maxPower")),
                        avg_speed_mps=avg_speed,
                        avg_pace_sec_km=_compute_pace_sec_km(avg_speed),
                        avg_cadence=_to_float(_get_first(lap_summary, "averageRunCadence", "averageCadence", "avgCadence")),
                        max_cadence=_to_float(_get_first(lap_summary, "maxRunCadence", "maxCadence")),
                        stroke_count=_to_int(_get_first(lap_summary, "strokeCount")),
                        swolf=_to_int(_get_first(lap_summary, "swolf")),
                        raw_lap_json=json.dumps(lap, ensure_ascii=True, default=str),
                    )
                )

            db.commit()
            existing_by_garmin_id[garmin_activity_id] = activity

            if activity.start_time is None or activity.duration_sec is None or activity.distance_m is None:
                logger.warning(
                    "Garmin activity %s still has missing core fields after normalization. summary_keys=%s summaryDTO_keys=%s",
                    garmin_activity_id,
                    sorted(detailed_summary.keys())[:40] if isinstance(detailed_summary, dict) else [],
                    sorted(summary_dto.keys())[:40] if isinstance(summary_dto, dict) else [],
                )
        except Exception as exc:
            db.rollback()
            errors.append(f"Activity {garmin_activity_id}: {exc}")

    return GarminSyncResult(
        athlete_name=athlete.name,
        found=found,
        inserted=inserted,
        existing=existing,
        errors=errors,
    )


def _get_sync_athlete(db: Session, athlete_id: int | None = None) -> Athlete:
    if athlete_id is not None:
        athlete = db.get(Athlete, athlete_id)
        if athlete is None:
            raise GarminServiceError("El atleta seleccionado no existe.")
        return athlete
    athlete = db.scalar(select(Athlete).where(Athlete.status == "active").order_by(Athlete.created_at.asc(), Athlete.id.asc()))
    if athlete is None:
        raise GarminServiceError("Create at least one athlete before syncing Garmin activities.")
    return athlete


def _get_first(source: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not isinstance(source, dict):
        return default
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


def _parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    cleaned = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _parse_end_time(summary: dict[str, Any]) -> datetime | None:
    end_value = _get_first(summary, "endTimeLocal", "endTimeGMT", "endTime")
    parsed = _parse_datetime(end_value)
    if parsed is not None:
        return parsed
    start_time = _parse_datetime(_get_first(summary, "startTimeLocal", "startTimeGMT", "startTime"))
    duration_sec = _to_int(_get_first(summary, "duration", "elapsedDuration"))
    if start_time is not None and duration_sec is not None:
        return start_time + timedelta(seconds=duration_sec)
    return None


def _extract_summary_dto(*sources: dict[str, Any]) -> dict[str, Any]:
    for source in sources:
        if isinstance(source, dict):
            value = source.get("summaryDTO")
            if isinstance(value, dict):
                return value
    return {}


def _extract_metadata_dto(*sources: dict[str, Any]) -> dict[str, Any]:
    for source in sources:
        if isinstance(source, dict):
            value = source.get("metadataDTO")
            if isinstance(value, dict):
                return value
    return {}


def _extract_lap_summary(lap: dict[str, Any]) -> dict[str, Any]:
    for key in ("summaryDTO", "lapSummary", "splitSummary", "summary"):
        value = lap.get(key)
        if isinstance(value, dict):
            return value
    return lap


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_pace_sec_km(speed_mps: float | None) -> float | None:
    if speed_mps is None or speed_mps <= 0:
        return None
    return 1000.0 / speed_mps


def _build_activity_values(
    athlete_id: int,
    garmin_activity_id: int,
    activity_summary: dict[str, Any],
    detailed_summary: dict[str, Any],
    details: dict[str, Any],
    summary_dto: dict[str, Any],
    metadata_dto: dict[str, Any],
    debug_payload: dict[str, Any],
) -> dict[str, Any]:
    avg_speed = _to_float(_first_nested(
        summary_dto,
        detailed_summary,
        activity_summary,
        keys=("averageSpeed", "avgSpeed"),
    ))

    return {
        "athlete_id": athlete_id,
        "garmin_activity_id": garmin_activity_id,
        "activity_name": _first_nested(detailed_summary, activity_summary, keys=("activityName", "activity_name")),
        "sport_type": _extract_sport_type(detailed_summary, activity_summary),
        "discipline_variant": _extract_discipline_variant(detailed_summary, activity_summary),
        "is_multisport": bool(
            _first_nested(
                detailed_summary,
                activity_summary,
                details,
                metadata_dto,
                keys=("isMultiSportParent", "isMultiSport", "isMultisport", "multiSport"),
                default=False,
            )
        ),
        "start_time": _parse_datetime(
            _first_nested(summary_dto, detailed_summary, activity_summary, keys=("startTimeLocal", "startTimeGMT", "startTime"))
        ),
        "end_time": _parse_end_time(summary_dto or detailed_summary),
        "duration_sec": _duration_to_seconds(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("duration", "elapsedDuration"))),
        "moving_duration_sec": _duration_to_seconds(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("movingDuration",))),
        "distance_m": _to_float(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("distance",))),
        "elevation_gain_m": _to_float(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("elevationGain",))),
        "elevation_loss_m": _to_float(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("elevationLoss",))),
        "avg_hr": _to_int(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("averageHR", "avgHR"))),
        "max_hr": _to_int(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("maxHR",))),
        "avg_power": _to_int(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("averagePower", "avgPower"))),
        "max_power": _to_int(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("maxPower",))),
        "normalized_power": _to_int(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("normalizedPower", "normPower"))),
        "avg_speed_mps": avg_speed,
        "max_speed_mps": _to_float(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("maxSpeed",))),
        "avg_pace_sec_km": _compute_pace_sec_km(avg_speed),
        "avg_cadence": _to_float(
            _first_nested(summary_dto, detailed_summary, activity_summary, keys=("averageRunCadence", "averageCadence", "avgCadence"))
        ),
        "max_cadence": _to_float(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("maxRunCadence", "maxCadence"))),
        "training_effect_aerobic": _to_float(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("trainingEffect", "aerobicTrainingEffect"))),
        "training_effect_anaerobic": _to_float(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("anaerobicTrainingEffect",))),
        "training_load": _to_float(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("activityTrainingLoad", "trainingLoad"))),
        "calories": _to_float(_first_nested(summary_dto, detailed_summary, activity_summary, keys=("calories",))),
        "avg_temperature_c": _to_float(_first_nested(details, summary_dto, detailed_summary, keys=("averageTemperature", "avgTemperature"))),
        "start_lat": _extract_start_coordinate(details, summary_dto, "lat"),
        "start_lon": _extract_start_coordinate(details, summary_dto, "lon"),
        "device_name": _extract_device_name(details, metadata_dto, detailed_summary),
        "raw_summary_json": json.dumps(debug_payload, ensure_ascii=True, default=str),
    }


def _first_nested(*sources: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for source in sources:
        value = _get_first(source, *keys, default=None)
        if value is not None:
            return value
    return default


def _duration_to_seconds(value: Any) -> int | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    return int(round(numeric))


def _extract_sport_type(*sources: dict[str, Any]) -> str | None:
    for source in sources:
        activity_type = _get_first(source, "activityType")
        if isinstance(activity_type, dict):
            value = _get_first(activity_type, "typeKey", "typeName", "parentTypeName")
            if isinstance(value, str):
                return value
        value = _get_first(source, "activityTypeDTO")
        if isinstance(value, dict):
            key = _get_first(value, "typeKey", "typeName", "parentTypeName")
            if isinstance(key, str):
                return key
    return None


def _extract_discipline_variant(*sources: dict[str, Any]) -> str | None:
    for source in sources:
        for container_key in ("activityType", "activityTypeDTO"):
            container = _get_first(source, container_key)
            if isinstance(container, dict):
                value = _get_first(container, "parentTypeName", "parentTypeKey")
                if isinstance(value, str):
                    return value
    return None


def _extract_start_coordinate(details: dict[str, Any], summary_dto: dict[str, Any], axis: str) -> float | None:
    axis_key = "Latitude" if axis == "lat" else "Longitude"
    direct = _to_float(_get_first(summary_dto, f"start{axis_key}", f"start{axis.capitalize()}"))
    if direct is not None:
        return direct

    metadata = _get_first(details, "metadataDTO")
    if isinstance(metadata, dict):
        direct = _to_float(_get_first(metadata, f"start{axis_key}", f"start{axis.capitalize()}"))
        if direct is not None:
            return direct

    summary_polyline = _get_first(details, "summaryDTO")
    if isinstance(summary_polyline, dict):
        direct = _to_float(_get_first(summary_polyline, f"start{axis_key}", f"start{axis.capitalize()}"))
        if direct is not None:
            return direct
    return None


def _extract_device_name(details: dict[str, Any], metadata_dto: dict[str, Any], summary: dict[str, Any]) -> str | None:
    for source in (details, metadata_dto, summary):
        device = _get_first(source, "deviceMetaDataDTO", "deviceDTO")
        if isinstance(device, dict):
            name = _get_first(device, "deviceName", "displayName")
            if isinstance(name, str):
                return name
    return None


def _infer_lap_type(lap: dict[str, Any]) -> str | None:
    for key in ("lapType", "lapTrigger", "intensityType"):
        value = _get_first(lap, key)
        if isinstance(value, str):
            return value.lower()
    return "unknown"
