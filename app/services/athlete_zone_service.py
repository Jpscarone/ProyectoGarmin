from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.athlete import Athlete
from app.services.garmin.profile_sync import load_athlete_garmin_snapshot, load_zone_payload


ZONE_NAMES = ["Z1", "Z2", "Z3", "Z4", "Z5"]
DEFAULT_RPE_LABELS = {
    "Z1": "Muy suave",
    "Z2": "Suave",
    "Z3": "Moderado",
    "Z4": "Fuerte",
    "Z5": "Maximo",
}


def build_zone_form_rows(athlete: Athlete) -> dict[str, list[dict[str, Any]]]:
    hr_rows = _rows_for_form(load_zone_payload(athlete.hr_zones_json).get("general"))
    power_rows = _rows_for_form(load_zone_payload(athlete.power_zones_json).get("general"))
    pace_rows = _rows_for_form(load_zone_payload(athlete.pace_zones_json).get("general"))
    rpe_rows = _rpe_rows_for_form(load_zone_payload(athlete.rpe_zones_json).get("general"))
    return {
        "hr_rows": hr_rows,
        "power_rows": power_rows,
        "pace_rows": pace_rows,
        "rpe_rows": rpe_rows,
    }


def update_athlete_zones_manual(
    db: Session,
    athlete: Athlete,
    hr_rows: list[dict[str, int | None]],
    power_rows: list[dict[str, int | None]],
    pace_rows: list[dict[str, int | None]],
    rpe_rows: list[dict[str, str | None]],
) -> list[str]:
    updated_blocks: list[str] = []

    normalized_hr = _normalize_rows(hr_rows)
    normalized_power = _normalize_rows(power_rows)
    normalized_pace = _normalize_rows(pace_rows)
    normalized_rpe = _normalize_rpe_rows(rpe_rows)

    if normalized_hr:
        athlete.hr_zones_json = json.dumps({"general": normalized_hr}, ensure_ascii=True)
        athlete.source_hr_zones = "manual"
        updated_blocks.append("zonas de frecuencia cardiaca")

    if normalized_power:
        athlete.power_zones_json = json.dumps({"general": normalized_power}, ensure_ascii=True)
        athlete.source_power_zones = "manual"
        updated_blocks.append("zonas de potencia")

    if normalized_pace:
        athlete.pace_zones_json = json.dumps({"general": normalized_pace}, ensure_ascii=True)
        athlete.source_pace_zones = "manual"
        updated_blocks.append("zonas de ritmo")

    if normalized_rpe:
        athlete.rpe_zones_json = json.dumps({"general": normalized_rpe}, ensure_ascii=True)
        athlete.source_rpe_zones = "manual"
        updated_blocks.append("zonas de esfuerzo percibido")

    if not updated_blocks:
        raise ValueError("Carga al menos una zona valida para guardar.")

    db.add(athlete)
    db.commit()
    db.refresh(athlete)
    return updated_blocks


def use_garmin_zones(db: Session, athlete: Athlete) -> list[str]:
    snapshot = load_athlete_garmin_snapshot(athlete)
    if not snapshot:
        raise ValueError("Primero tenes que comparar el atleta con Garmin.")

    updated_blocks: list[str] = []

    hr_zones = snapshot.get("hr_zones")
    if hr_zones:
        athlete.hr_zones_json = json.dumps(hr_zones, ensure_ascii=True)
        athlete.source_hr_zones = "garmin"
        updated_blocks.append("zonas de frecuencia cardiaca")

    power_zones = snapshot.get("power_zones")
    if power_zones:
        athlete.power_zones_json = json.dumps(power_zones, ensure_ascii=True)
        athlete.source_power_zones = "garmin"
        updated_blocks.append("zonas de potencia")

    pace_zones = snapshot.get("pace_zones")
    if pace_zones:
        athlete.pace_zones_json = json.dumps(pace_zones, ensure_ascii=True)
        athlete.source_pace_zones = "garmin"
        updated_blocks.append("zonas de ritmo")

    if not updated_blocks:
        raise ValueError("No hay zonas disponibles en el snapshot Garmin.")

    db.add(athlete)
    db.commit()
    db.refresh(athlete)
    return updated_blocks


def recalculate_athlete_zones(db: Session, athlete: Athlete) -> list[str]:
    updated_blocks: list[str] = []

    if athlete.max_hr:
        hr_zones = _calculate_hr_zones(athlete.max_hr)
        athlete.hr_zones_json = json.dumps({"general": hr_zones}, ensure_ascii=True)
        athlete.source_hr_zones = "calculated"
        updated_blocks.append("zonas de frecuencia cardiaca")

    if athlete.cycling_ftp:
        power_zones = _calculate_power_zones(athlete.cycling_ftp)
        athlete.power_zones_json = json.dumps({"general": power_zones}, ensure_ascii=True)
        athlete.source_power_zones = "calculated"
        updated_blocks.append("zonas de potencia")

    if not updated_blocks:
        raise ValueError("Para recalcular zonas hace falta FC maxima o FTP ciclismo.")

    db.add(athlete)
    db.commit()
    db.refresh(athlete)
    return updated_blocks


def zone_source_label(value: str | None) -> str:
    labels = {
        "manual": "Manual",
        "garmin": "Garmin",
        "calculated": "Calculado",
    }
    return labels.get((value or "").strip().lower(), "Sin datos")


def _rows_for_form(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized = rows or []
    output: list[dict[str, Any]] = []
    for index, zone_name in enumerate(ZONE_NAMES):
        row = normalized[index] if index < len(normalized) else {}
        output.append(
            {
                "name": zone_name,
                "min": row.get("min"),
                "max": row.get("max"),
            }
        )
    return output


def _rpe_rows_for_form(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized = rows or []
    output: list[dict[str, Any]] = []
    for index, zone_name in enumerate(ZONE_NAMES):
        row = normalized[index] if index < len(normalized) else {}
        output.append(
            {
                "name": zone_name,
                "label": row.get("label") or DEFAULT_RPE_LABELS[zone_name],
            }
        )
    return output


def _normalize_rows(rows: list[dict[str, int | None]]) -> list[dict[str, int | None]]:
    normalized: list[dict[str, int | None]] = []
    for index, zone_name in enumerate(ZONE_NAMES):
        row = rows[index] if index < len(rows) else {}
        minimum = row.get("min")
        maximum = row.get("max")
        if minimum is None and maximum is None:
            continue
        normalized.append({"name": zone_name, "min": minimum, "max": maximum})
    return normalized


def _normalize_rpe_rows(rows: list[dict[str, str | None]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, zone_name in enumerate(ZONE_NAMES):
        row = rows[index] if index < len(rows) else {}
        label = str(row.get("label") or "").strip()
        if not label:
            label = DEFAULT_RPE_LABELS[zone_name]
        normalized.append({"name": zone_name, "label": label})
    return normalized


def _calculate_hr_zones(max_hr: int) -> list[dict[str, int]]:
    ranges = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.00)]
    rows: list[dict[str, int]] = []
    for index, (low, high) in enumerate(ranges):
        rows.append(
            {
                "name": ZONE_NAMES[index],
                "min": int(round(max_hr * low)),
                "max": int(round(max_hr * high)),
            }
        )
    return rows


def _calculate_power_zones(ftp: int) -> list[dict[str, int | None]]:
    ranges = [(0.00, 0.55), (0.55, 0.75), (0.75, 0.90), (0.90, 1.05), (1.05, None)]
    rows: list[dict[str, int | None]] = []
    for index, (low, high) in enumerate(ranges):
        rows.append(
            {
                "name": ZONE_NAMES[index],
                "min": int(round(ftp * low)),
                "max": int(round(ftp * high)) if high is not None else None,
            }
        )
    return rows
