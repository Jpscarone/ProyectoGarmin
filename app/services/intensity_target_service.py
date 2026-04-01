from __future__ import annotations

from typing import Any

from app.db.models.athlete import Athlete
from app.services.garmin.profile_sync import load_zone_payload


SUPPORTED_TARGET_TYPES = {"hr", "pace", "power", "rpe"}


def normalize_target_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in SUPPORTED_TARGET_TYPES else None


def infer_session_target_type(
    *,
    target_type: str | None,
    target_hr_zone: str | None,
    target_pace_zone: str | None,
    target_power_zone: str | None,
    target_rpe_zone: str | None,
) -> str | None:
    explicit = normalize_target_type(target_type)
    if explicit:
        return explicit
    if target_power_zone:
        return "power"
    if target_pace_zone:
        return "pace"
    if target_hr_zone:
        return "hr"
    if target_rpe_zone:
        return "rpe"
    return None


def infer_step_target_type(
    *,
    target_type: str | None,
    target_hr_zone: str | None,
    target_hr_min: int | None,
    target_hr_max: int | None,
    target_power_zone: str | None,
    target_power_min: int | None,
    target_power_max: int | None,
    target_pace_zone: str | None,
    target_pace_min_sec_km: int | None,
    target_pace_max_sec_km: int | None,
    target_rpe_zone: str | None,
) -> str | None:
    explicit = normalize_target_type(target_type)
    if explicit:
        return explicit
    if target_power_zone or target_power_min is not None or target_power_max is not None:
        return "power"
    if target_pace_zone or target_pace_min_sec_km is not None or target_pace_max_sec_km is not None:
        return "pace"
    if target_hr_zone or target_hr_min is not None or target_hr_max is not None:
        return "hr"
    if target_rpe_zone:
        return "rpe"
    return None


def normalize_session_target_fields(data: dict[str, Any]) -> dict[str, Any]:
    target_type = infer_session_target_type(
        target_type=data.get("target_type"),
        target_hr_zone=data.get("target_hr_zone"),
        target_pace_zone=data.get("target_pace_zone"),
        target_power_zone=data.get("target_power_zone"),
        target_rpe_zone=data.get("target_rpe_zone"),
    )
    data["target_type"] = target_type
    if target_type != "hr":
        data["target_hr_zone"] = None
    if target_type != "pace":
        data["target_pace_zone"] = None
    if target_type != "power":
        data["target_power_zone"] = None
    if target_type != "rpe":
        data["target_rpe_zone"] = None
    return data


def normalize_step_target_fields(data: dict[str, Any], athlete: Athlete | None) -> dict[str, Any]:
    target_type = infer_step_target_type(
        target_type=data.get("target_type"),
        target_hr_zone=data.get("target_hr_zone"),
        target_hr_min=data.get("target_hr_min"),
        target_hr_max=data.get("target_hr_max"),
        target_power_zone=data.get("target_power_zone"),
        target_power_min=data.get("target_power_min"),
        target_power_max=data.get("target_power_max"),
        target_pace_zone=data.get("target_pace_zone"),
        target_pace_min_sec_km=data.get("target_pace_min_sec_km"),
        target_pace_max_sec_km=data.get("target_pace_max_sec_km"),
        target_rpe_zone=data.get("target_rpe_zone"),
    )
    data["target_type"] = target_type

    if target_type == "hr" and data.get("target_hr_zone") and athlete is not None:
        minimum, maximum = _zone_min_max(load_zone_payload(athlete.hr_zones_json), data["target_hr_zone"])
        if minimum is not None or maximum is not None:
            data["target_hr_min"] = minimum
            data["target_hr_max"] = maximum
    elif target_type != "hr":
        data["target_hr_zone"] = None
        data["target_hr_min"] = None
        data["target_hr_max"] = None

    if target_type == "power" and data.get("target_power_zone") and athlete is not None:
        minimum, maximum = _zone_min_max(load_zone_payload(athlete.power_zones_json), data["target_power_zone"])
        if minimum is not None or maximum is not None:
            data["target_power_min"] = minimum
            data["target_power_max"] = maximum
    elif target_type != "power":
        data["target_power_zone"] = None
        data["target_power_min"] = None
        data["target_power_max"] = None

    if target_type == "pace" and data.get("target_pace_zone") and athlete is not None:
        minimum, maximum = _zone_min_max(load_zone_payload(athlete.pace_zones_json), data["target_pace_zone"])
        if minimum is not None or maximum is not None:
            data["target_pace_min_sec_km"] = minimum
            data["target_pace_max_sec_km"] = maximum
    elif target_type != "pace":
        data["target_pace_zone"] = None
        data["target_pace_min_sec_km"] = None
        data["target_pace_max_sec_km"] = None

    if target_type != "rpe":
        data["target_rpe_zone"] = None

    return data


def _zone_min_max(zone_payload: dict[str, list[dict[str, Any]]], zone_name: str) -> tuple[int | None, int | None]:
    general_rows = zone_payload.get("general", [])
    for row in general_rows:
        if str(row.get("name")) == zone_name:
            return _optional_int(row.get("min")), _optional_int(row.get("max"))
    return None, None


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
