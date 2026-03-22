from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.athlete import Athlete
from app.services.garmin.auth import GarminServiceError, get_garmin_auth_context
from app.services.garmin.client import GarminClient


GENERAL_FIELD_LABELS: dict[str, str] = {
    "height_cm": "Altura",
    "weight_kg": "Peso",
    "max_hr": "FC maxima",
    "resting_hr": "FC reposo",
    "lactate_threshold_hr": "FC umbral lactato",
    "running_threshold_pace_sec_km": "Ritmo umbral running",
    "cycling_ftp": "FTP ciclismo",
    "vo2max": "VO2max",
}


def compare_athlete_with_garmin(db: Session, athlete: Athlete, settings: Settings) -> dict[str, Any]:
    snapshot = fetch_garmin_profile_snapshot(settings)
    athlete.garmin_profile_snapshot_json = json.dumps(snapshot, ensure_ascii=True)
    athlete.garmin_profile_last_synced_at = datetime.now(timezone.utc)
    db.add(athlete)
    db.commit()
    db.refresh(athlete)
    return build_athlete_garmin_comparison(athlete)


def build_athlete_garmin_comparison(athlete: Athlete) -> dict[str, Any]:
    snapshot = load_athlete_garmin_snapshot(athlete)
    local_hr_zones = load_zone_payload(athlete.hr_zones_json)
    local_power_zones = load_zone_payload(athlete.power_zones_json)

    if not snapshot:
        return {
            "has_snapshot": False,
            "general_rows": [],
            "hr_zone_rows": [],
            "power_zone_rows": [],
            "has_differences": False,
            "has_general_differences": False,
            "has_hr_zone_differences": False,
            "has_power_zone_differences": False,
            "garmin_summary": {},
            "local_hr_zones": local_hr_zones,
            "local_power_zones": local_power_zones,
        }

    garmin_general = snapshot.get("general", {}) if isinstance(snapshot.get("general"), dict) else {}
    garmin_hr_zones = snapshot.get("hr_zones", {}) if isinstance(snapshot.get("hr_zones"), dict) else {}
    garmin_power_zones = snapshot.get("power_zones", {}) if isinstance(snapshot.get("power_zones"), dict) else {}

    general_rows: list[dict[str, Any]] = []
    for field_name, label in GENERAL_FIELD_LABELS.items():
        local_value = getattr(athlete, field_name)
        garmin_value = garmin_general.get(field_name)
        if local_value is None and garmin_value is None:
            continue
        is_different = _values_differ(local_value, garmin_value)
        general_rows.append(
            {
                "field_name": field_name,
                "label": label,
                "local_value": format_general_value(field_name, local_value),
                "garmin_value": format_general_value(field_name, garmin_value),
                "is_different": is_different,
                "suggested_action": "actualizar" if is_different and garmin_value is not None else "sin cambios",
            }
        )

    hr_zone_rows = _build_zone_rows(local_hr_zones, garmin_hr_zones)
    power_zone_rows = _build_zone_rows(local_power_zones, garmin_power_zones)

    has_general_differences = any(row["is_different"] for row in general_rows)
    has_hr_zone_differences = any(row["is_different"] for row in hr_zone_rows)
    has_power_zone_differences = any(row["is_different"] for row in power_zone_rows)

    return {
        "has_snapshot": True,
        "general_rows": general_rows,
        "hr_zone_rows": hr_zone_rows,
        "power_zone_rows": power_zone_rows,
        "has_differences": has_general_differences or has_hr_zone_differences or has_power_zone_differences,
        "has_general_differences": has_general_differences,
        "has_hr_zone_differences": has_hr_zone_differences,
        "has_power_zone_differences": has_power_zone_differences,
        "garmin_summary": {
            "available_fields": [GENERAL_FIELD_LABELS[field] for field, value in garmin_general.items() if value is not None and field in GENERAL_FIELD_LABELS],
            "has_hr_zones": bool(garmin_hr_zones),
            "has_power_zones": bool(garmin_power_zones),
            "source_keys": list(snapshot.get("source_payload_keys", [])),
        },
        "local_hr_zones": local_hr_zones,
        "local_power_zones": local_power_zones,
        "garmin_hr_zones": garmin_hr_zones,
        "garmin_power_zones": garmin_power_zones,
    }


def apply_garmin_changes(db: Session, athlete: Athlete, scope: str) -> list[str]:
    snapshot = load_athlete_garmin_snapshot(athlete)
    if not snapshot:
        raise ValueError("Primero tenes que comparar el atleta con Garmin.")

    normalized_scope = (scope or "all").strip().lower()
    valid_scopes = {"all", "general", "hr_zones", "power_zones"}
    if normalized_scope not in valid_scopes:
        raise ValueError("El bloque seleccionado no es valido.")

    applied_blocks: list[str] = []
    general = snapshot.get("general", {}) if isinstance(snapshot.get("general"), dict) else {}

    if normalized_scope in {"all", "general"}:
        applied_general = False
        for field_name in GENERAL_FIELD_LABELS:
            garmin_value = general.get(field_name)
            if garmin_value is not None:
                setattr(athlete, field_name, garmin_value)
                applied_general = True
        if applied_general:
            applied_blocks.append("datos generales")

    if normalized_scope in {"all", "hr_zones"}:
        hr_zones = snapshot.get("hr_zones")
        if hr_zones:
            athlete.hr_zones_json = json.dumps(hr_zones, ensure_ascii=True)
            athlete.source_hr_zones = "garmin"
            applied_blocks.append("zonas de frecuencia cardiaca")

    if normalized_scope in {"all", "power_zones"}:
        power_zones = snapshot.get("power_zones")
        if power_zones:
            athlete.power_zones_json = json.dumps(power_zones, ensure_ascii=True)
            athlete.source_power_zones = "garmin"
            applied_blocks.append("zonas de potencia")

    if not applied_blocks:
        raise ValueError("No habia datos de Garmin disponibles para aplicar en ese bloque.")

    db.add(athlete)
    db.commit()
    db.refresh(athlete)
    return applied_blocks


def load_athlete_garmin_snapshot(athlete: Athlete) -> dict[str, Any]:
    raw = athlete.garmin_profile_snapshot_json
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_zone_payload(raw_value: str | None) -> dict[str, list[dict[str, Any]]]:
    if not raw_value:
        return {}
    try:
        data = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(sport_key): list(zone_rows)
        for sport_key, zone_rows in data.items()
        if isinstance(zone_rows, list)
    }


def fetch_garmin_profile_snapshot(settings: Settings) -> dict[str, Any]:
    auth_context = get_garmin_auth_context(settings)
    client = GarminClient(auth_context.client)
    payloads = client.get_profile_payloads()

    user_profile = payloads.get("user_profile", {})
    user_data = user_profile.get("userData", {}) if isinstance(user_profile, dict) else {}
    lactate_threshold = payloads.get("lactate_threshold", {})
    lactate_speed_and_hr = lactate_threshold.get("speed_and_heart_rate", {}) if isinstance(lactate_threshold, dict) else {}
    cycling_ftp = payloads.get("cycling_ftp", {})

    hr_zones = _extract_zone_block(payloads, ("hr_zones", "heartRateZones", "heartRateZone", "runningHeartRateZones", "cyclingHeartRateZones"))
    power_zones = _extract_zone_block(payloads, ("power_zones", "powerZones", "cyclingPowerZones", "runningPowerZones"))

    running_threshold_speed = _first_value(
        user_data.get("lactateThresholdSpeed"),
        lactate_speed_and_hr.get("speed"),
    )

    snapshot = {
        "general": {
            "height_cm": _as_float(user_data.get("height")),
            "weight_kg": _normalize_weight_kg(user_data.get("weight")),
            "max_hr": _first_int(user_data.get("maxHeartRate"), user_data.get("maximumHeartRate")),
            "resting_hr": _first_int(user_data.get("restingHeartRate"), user_data.get("restHr")),
            "lactate_threshold_hr": _first_int(
                user_data.get("lactateThresholdHeartRate"),
                lactate_speed_and_hr.get("heartRate"),
            ),
            "running_threshold_pace_sec_km": _pace_from_garmin_speed(running_threshold_speed),
            "cycling_ftp": _first_int(cycling_ftp.get("functionalThresholdPower")),
            "vo2max": _first_float(user_data.get("vo2MaxRunning"), user_data.get("vo2MaxCycling")),
        },
        "hr_zones": hr_zones,
        "power_zones": power_zones,
        "source_payload_keys": sorted(payloads.keys()),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw_payloads": payloads,
    }
    return snapshot


def format_general_value(field_name: str, value: Any) -> str:
    if value is None:
        return "-"
    if field_name == "height_cm":
        return f"{float(value):.0f} cm"
    if field_name == "weight_kg":
        return f"{float(value):.1f} kg"
    if field_name == "vo2max":
        return f"{float(value):.1f}"
    if field_name == "running_threshold_pace_sec_km":
        total_seconds = int(value)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d} /km"
    return str(value)


def format_zone_label(zone: Mapping[str, Any] | None) -> str:
    if not zone:
        return "-"
    minimum = zone.get("min")
    maximum = zone.get("max")
    if minimum is None and maximum is None:
        return "-"
    if minimum is None:
        return f"hasta {maximum}"
    if maximum is None:
        return f"{minimum}+"
    return f"{minimum} - {maximum}"


def _build_zone_rows(
    local_zones: dict[str, list[dict[str, Any]]],
    garmin_zones: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    sport_keys = sorted(set(local_zones.keys()) | set(garmin_zones.keys()))
    rows: list[dict[str, Any]] = []

    for sport_key in sport_keys:
        local_zone_list = local_zones.get(sport_key, [])
        garmin_zone_list = garmin_zones.get(sport_key, [])
        max_len = max(len(local_zone_list), len(garmin_zone_list))
        for index in range(max_len):
            local_zone = local_zone_list[index] if index < len(local_zone_list) else None
            garmin_zone = garmin_zone_list[index] if index < len(garmin_zone_list) else None
            zone_name = (
                (garmin_zone or {}).get("name")
                or (local_zone or {}).get("name")
                or f"Z{index + 1}"
            )
            is_different = _values_differ(local_zone, garmin_zone)
            rows.append(
                {
                    "sport": sport_key,
                    "zone_name": zone_name,
                    "local_value": format_zone_label(local_zone),
                    "garmin_value": format_zone_label(garmin_zone),
                    "is_different": is_different,
                    "suggested_action": "revisar" if is_different and garmin_zone is not None else "sin cambios",
                }
            )
    return rows


def _extract_zone_block(payloads: Mapping[str, Any], candidate_keys: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized_key = key.lower()
                if any(candidate.lower() == normalized_key for candidate in candidate_keys):
                    normalized = _normalize_zone_payload(item)
                    if normalized:
                        found.update(normalized)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payloads)
    return found


def _normalize_zone_payload(value: Any) -> dict[str, list[dict[str, Any]]]:
    if isinstance(value, dict):
        if all(isinstance(item, list) for item in value.values()):
            normalized: dict[str, list[dict[str, Any]]] = {}
            for sport_key, rows in value.items():
                normalized_rows = _normalize_zone_rows(rows)
                if normalized_rows:
                    normalized[str(sport_key)] = normalized_rows
            return normalized
        normalized_rows = _normalize_zone_rows(value.get("zones"))
        if normalized_rows:
            sport_key = str(value.get("sport") or value.get("sportType") or "general")
            return {sport_key: normalized_rows}

    normalized_rows = _normalize_zone_rows(value)
    return {"general": normalized_rows} if normalized_rows else {}


def _normalize_zone_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized_rows: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            continue
        zone_name = row.get("name") or row.get("zoneName") or row.get("zoneNumber") or f"Z{index + 1}"
        minimum = _first_int(row.get("min"), row.get("from"), row.get("low"), row.get("start"))
        maximum = _first_int(row.get("max"), row.get("to"), row.get("high"), row.get("end"))
        normalized_rows.append(
            {
                "name": str(zone_name),
                "min": minimum,
                "max": maximum,
            }
        )
    return normalized_rows


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _as_float(value)
        if parsed is not None:
            return parsed
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        try:
            if value is None:
                continue
            return int(round(float(value)))
        except (TypeError, ValueError):
            continue
    return None


def _normalize_weight_kg(value: Any) -> float | None:
    parsed = _as_float(value)
    if parsed is None:
        return None
    if parsed > 1000:
        return round(parsed / 1000, 1)
    return round(parsed, 1)


def _pace_from_garmin_speed(value: Any) -> int | None:
    parsed = _as_float(value)
    if parsed is None or parsed <= 0:
        return None
    # Garmin devuelve este valor en km/min para lactate threshold.
    return int(round(60 / parsed))


def _values_differ(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return False
    if isinstance(left, float) or isinstance(right, float):
        try:
            return round(float(left or 0), 3) != round(float(right or 0), 3)
        except (TypeError, ValueError):
            return left != right
    return left != right
