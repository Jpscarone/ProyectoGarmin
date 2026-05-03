from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.training_day import TrainingDay
from app.schemas.planned_session import PlannedSessionCreate
from app.schemas.planned_session_step import PlannedSessionStepCreate
from app.schemas.training_day import TrainingDayCreate
from app.services.garmin.profile_sync import load_zone_payload
from app.services.intensity_target_service import normalize_step_target_fields
from app.services.planned_session_service import create_planned_session
from app.services.planned_session_step_service import create_step
from app.services.session_group_service import create_inline_group
from app.services.training_day_service import create_training_day, get_training_day, get_training_day_by_plan_and_date
from app.services.training_plan_service import get_training_plan
from app.services.session_import_parser import ImportBlock, ImportGroup, ImportRepeat, ImportSession, parse_session_import_text
from app.services.session_import_validator import validate_import_payload


SUPPORTED_SPORTS = {"running", "cycling", "swimming", "strength", "walking", "other"}
INTENSITY_TYPES = {"hr", "pace", "power", "rpe"}
TIME_UNITS = {"seg", "s", "sec", "min", "h"}
DISTANCE_UNITS = {"m", "km"}
PACE_PATTERN = re.compile(r"^\s*(\d{1,2}):(\d{2})(?:\s*/\s*km)?\s*$", re.IGNORECASE)


@dataclass
class ImportPreviewResult:
    ok: bool
    errors: list[dict[str, Any]]
    preview: dict[str, Any] | None


@dataclass
class ImportCreateResult:
    ok: bool
    errors: list[dict[str, Any]]
    created_sessions: int
    created_groups: int
    redirect_url: str | None


def preview_session_import(
    db: Session,
    *,
    training_day_id: int | None,
    training_plan_id: int | None,
    base_date_str: str | None,
    raw_text: str,
) -> ImportPreviewResult:
    parsed = parse_session_import_text(raw_text or "")
    base_date = _parse_date(base_date_str)

    validation = validate_import_payload(
        sessions=parsed.sessions,
        groups=parsed.groups,
        base_date=base_date,
    )
    errors = parsed.errors + validation.errors
    if errors:
        return ImportPreviewResult(ok=False, errors=_format_errors(errors), preview=None)

    training_plan = _resolve_training_plan(db, training_day_id, training_plan_id, base_date)
    if training_plan is None and training_day_id is None:
        return ImportPreviewResult(
            ok=False,
            errors=[{"line": "-", "message": "No se pudo resolver el plan para importar sesiones."}],
            preview=None,
        )
    athlete = training_plan.athlete if training_plan else None
    pace_zones = _load_zone_map(athlete, "pace")
    hr_zones = _load_zone_map(athlete, "hr")

    preview = _build_preview_payload(
        groups=parsed.groups,
        sessions=parsed.sessions,
        base_date=base_date,
        pace_zones=pace_zones,
        hr_zones=hr_zones,
    )
    return ImportPreviewResult(ok=True, errors=[], preview=preview)


def create_session_import(
    db: Session,
    *,
    training_day_id: int | None,
    training_plan_id: int | None,
    base_date_str: str | None,
    raw_text: str,
    return_to: str | None = None,
    return_month: str | None = None,
    return_selected_date: str | None = None,
) -> ImportCreateResult:
    parsed = parse_session_import_text(raw_text or "")
    base_date = _parse_date(base_date_str)
    validation = validate_import_payload(
        sessions=parsed.sessions,
        groups=parsed.groups,
        base_date=base_date,
    )
    errors = parsed.errors + validation.errors
    if errors:
        return ImportCreateResult(ok=False, errors=_format_errors(errors), created_sessions=0, created_groups=0, redirect_url=None)

    training_plan = _resolve_training_plan(db, training_day_id, training_plan_id, base_date)
    athlete = training_plan.athlete if training_plan else None
    pace_zones = _load_zone_map(athlete, "pace")
    hr_zones = _load_zone_map(athlete, "hr")

    created_sessions = 0
    created_groups = 0
    next_order_by_day: dict[int, int] = {}

    for group in parsed.groups:
        group_date = _resolve_session_date(group_date=_parse_date(group.date), session_date=None, base_date=base_date)
        training_day = _resolve_training_day(db, training_day_id, training_plan, group_date)
        session_group = create_inline_group(
            db,
            training_day_id=training_day.id,
            name=group.name or "Grupo importado",
            notes=group.notes,
        )
        created_groups += 1
        for session in group.sessions:
            created_sessions += _create_import_session(
                db,
                session=session,
                training_plan=training_plan,
                training_day=training_day,
                session_group_id=session_group.id,
                base_date=group_date,
                pace_zones=pace_zones,
                hr_zones=hr_zones,
                next_order_by_day=next_order_by_day,
            )

    for session in parsed.sessions:
        session_date = _resolve_session_date(group_date=None, session_date=_parse_date(session.date), base_date=base_date)
        training_day = _resolve_training_day(db, training_day_id, training_plan, session_date)
        created_sessions += _create_import_session(
            db,
            session=session,
            training_plan=training_plan,
            training_day=training_day,
            session_group_id=None,
            base_date=session_date,
            pace_zones=pace_zones,
            hr_zones=hr_zones,
            next_order_by_day=next_order_by_day,
        )

    redirect_url = _build_import_redirect_url(
        training_day_id=training_day_id,
        training_plan_id=training_plan.id if training_plan else None,
        base_date=base_date,
        return_to=return_to,
        return_month=return_month,
        return_selected_date=return_selected_date,
    )
    return ImportCreateResult(
        ok=True,
        errors=[],
        created_sessions=created_sessions,
        created_groups=created_groups,
        redirect_url=redirect_url,
    )


def _build_preview_payload(
    *,
    groups: list[ImportGroup],
    sessions: list[ImportSession],
    base_date: date | None,
    pace_zones: dict[str, dict[str, Any]],
    hr_zones: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    preview_groups = []
    for group in groups:
        group_date = _resolve_session_date(_parse_date(group.date), None, base_date)
        group_preview_sessions = [
            _build_session_preview(session, group_date, pace_zones, hr_zones) for session in group.sessions
        ]
        preview_groups.append(
            {
                "name": group.name or "Grupo sin nombre",
                "date": group_date.isoformat() if group_date else "-",
                "notes": group.notes or "",
                "sessions": group_preview_sessions,
            }
        )

    preview_sessions = [
        _build_session_preview(session, _resolve_session_date(None, _parse_date(session.date), base_date), pace_zones, hr_zones)
        for session in sessions
    ]

    return {
        "groups": preview_groups,
        "sessions": preview_sessions,
    }


def _build_session_preview(
    session: ImportSession,
    resolved_date: date | None,
    pace_zones: dict[str, dict[str, Any]],
    hr_zones: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    duration_sec, distance_m, duration_est, distance_est, blocks_preview = _summarize_blocks(
        session.blocks,
        pace_zones,
        hr_zones,
    )
    return {
        "date": resolved_date.isoformat() if resolved_date else "-",
        "sport": (session.sport or "").strip().lower(),
        "name": session.name or "Sesion sin nombre",
        "notes": session.notes or "",
        "duration": _format_duration(duration_sec),
        "distance": _format_distance(distance_m),
        "duration_estimated": duration_est,
        "distance_estimated": distance_est,
        "blocks": blocks_preview,
    }


def _summarize_blocks(
    blocks: list[ImportBlock | ImportRepeat],
    pace_zones: dict[str, dict[str, Any]],
    hr_zones: dict[str, dict[str, Any]],
) -> tuple[int | None, int | None, bool, bool, list[dict[str, Any]]]:
    total_seconds = 0
    total_distance = 0
    has_duration = False
    has_distance = False
    duration_estimated = False
    distance_estimated = False
    preview_blocks: list[dict[str, Any]] = []

    for block in blocks:
        if isinstance(block, ImportRepeat):
            repeat_preview = []
            repeat_seconds = 0
            repeat_distance = 0
            repeat_duration_est = False
            repeat_distance_est = False
            for nested in block.blocks:
                seconds, meters, sec_est, dist_est = _block_metrics(nested, pace_zones, hr_zones)
                repeat_preview.append(_block_preview(nested, seconds, meters, sec_est, dist_est))
                if seconds is not None:
                    repeat_seconds += seconds
                    has_duration = True
                if meters is not None:
                    repeat_distance += meters
                    has_distance = True
                repeat_duration_est = repeat_duration_est or sec_est
                repeat_distance_est = repeat_distance_est or dist_est
            if block.count:
                total_seconds += repeat_seconds * block.count
                total_distance += repeat_distance * block.count
            duration_estimated = duration_estimated or repeat_duration_est
            distance_estimated = distance_estimated or repeat_distance_est
            preview_blocks.append(
                {
                    "kind": "repeat",
                    "count": block.count or 0,
                    "items": repeat_preview,
                }
            )
            continue

        seconds, meters, sec_est, dist_est = _block_metrics(block, pace_zones, hr_zones)
        preview_blocks.append(_block_preview(block, seconds, meters, sec_est, dist_est))
        if seconds is not None:
            total_seconds += seconds
            has_duration = True
        if meters is not None:
            total_distance += meters
            has_distance = True
        duration_estimated = duration_estimated or sec_est
        distance_estimated = distance_estimated or dist_est

    return (
        total_seconds if has_duration else None,
        total_distance if has_distance else None,
        duration_estimated,
        distance_estimated,
        preview_blocks,
    )


def _block_preview(
    block: ImportBlock,
    seconds: int | None,
    meters: int | None,
    sec_est: bool,
    dist_est: bool,
) -> dict[str, Any]:
    intensity = _normalize_intensity(block.intensity)
    zone = _normalize_zone(block.zone)
    return {
        "value": block.value or "",
        "unit": _normalize_unit(block.unit),
        "intensity": intensity,
        "zone": zone,
        "target_label": _describe_block_target(block),
        "notes": block.notes or "",
        "duration": _format_duration(seconds),
        "distance": _format_distance(meters),
        "duration_estimated": sec_est,
        "distance_estimated": dist_est,
    }


def _block_metrics(
    block: ImportBlock,
    pace_zones: dict[str, dict[str, Any]],
    hr_zones: dict[str, dict[str, Any]],
) -> tuple[int | None, int | None, bool, bool]:
    unit = _normalize_unit(block.unit)
    value = _parse_float(block.value)
    if unit is None or value is None:
        return None, None, False, False

    duration_sec: int | None = None
    distance_m: int | None = None
    if unit in TIME_UNITS:
        duration_sec = _to_seconds(unit, value)
    elif unit in DISTANCE_UNITS:
        distance_m = _to_meters(unit, value)

    intensity = _normalize_intensity(block.intensity)
    zone = _normalize_zone(block.zone)
    pace_sec = _resolve_block_pace_seconds(block, intensity, zone, pace_zones, hr_zones)

    duration_estimated = False
    distance_estimated = False
    if pace_sec:
        if duration_sec is not None and distance_m is None:
            distance_m = int(round((duration_sec / pace_sec) * 1000))
            distance_estimated = True
        elif distance_m is not None and duration_sec is None:
            duration_sec = int(round((distance_m / 1000) * pace_sec))
            duration_estimated = True
    return duration_sec, distance_m, duration_estimated, distance_estimated


def _create_import_session(
    db: Session,
    *,
    session: ImportSession,
    training_plan,
    training_day: TrainingDay,
    session_group_id: int | None,
    base_date: date | None,
    pace_zones: dict[str, dict[str, Any]],
    hr_zones: dict[str, dict[str, Any]],
    next_order_by_day: dict[int, int],
) -> int:
    session_date = _resolve_session_date(None, _parse_date(session.date), base_date)
    if session_date is None:
        return 0

    duration_sec, distance_m, _, _, _ = _summarize_blocks(session.blocks, pace_zones, hr_zones)
    expected_duration_min = int(round(duration_sec / 60)) if duration_sec is not None else None
    expected_distance_km = round(distance_m / 1000, 2) if distance_m is not None else None

    sport_type = (session.sport or "").strip().lower()
    session_order = _next_session_order(training_day.id, training_day, next_order_by_day)
    target_type = _infer_session_target_type(session.blocks)
    target_zone = _infer_session_target_zone(session.blocks)

    planned_session = create_planned_session(
        db,
        PlannedSessionCreate(
            training_day_id=training_day.id,
            sport_type=sport_type or None,
            name=session.name or "Sesion importada",
            description_text=session.notes or None,
            session_type=None,
            session_order=session_order,
            planned_start_time=None,
            session_group_id=session_group_id,
            expected_duration_min=expected_duration_min,
            expected_distance_km=expected_distance_km,
            expected_elevation_gain_m=None,
            target_type=target_type,
            target_hr_zone=target_zone if target_type == "hr" else None,
            target_pace_zone=target_zone if target_type == "pace" else None,
            target_power_zone=target_zone if target_type == "power" else None,
            target_rpe_zone=target_zone if target_type == "rpe" else None,
            target_notes=session.notes or None,
            is_key_session=False,
        )
    )

    step_order = 1
    for block in session.blocks:
        if isinstance(block, ImportRepeat):
            repeat_count = block.count or 1
            for nested_index, nested in enumerate(block.blocks, start=1):
                step_order = _create_step_from_block(
                    db,
                    planned_session,
                    nested,
                    step_order=step_order,
                    repeat_count=repeat_count,
                    step_type=_infer_repeat_step_type(nested, nested_index),
                )
            continue
        step_order = _create_step_from_block(
            db,
            planned_session,
            block,
            step_order=step_order,
            repeat_count=None,
            step_type=_infer_simple_step_type(block),
        )

    return 1


def _create_step_from_block(
    db: Session,
    planned_session,
    block: ImportBlock,
    *,
    step_order: int,
    repeat_count: int | None,
    step_type: str,
) -> int:
    unit = _normalize_unit(block.unit)
    value = _parse_float(block.value)
    if unit is None or value is None:
        return step_order

    duration_sec = _to_seconds(unit, value) if unit in TIME_UNITS else None
    distance_m = _to_meters(unit, value) if unit in DISTANCE_UNITS else None
    intensity = _normalize_intensity(block.intensity)
    zone = _normalize_zone(block.zone)
    notes = block.notes or _default_block_target_note(block, intensity, zone)

    step_target_fields = _step_target_fields_from_block(block, intensity, zone)

    step_payload = normalize_step_target_fields(
        {
            "planned_session_id": planned_session.id,
            "step_order": step_order,
            "step_type": step_type,
            "repeat_count": repeat_count,
            "duration_sec": duration_sec,
            "distance_m": distance_m,
            "target_type": intensity,
            **step_target_fields,
            "target_notes": notes,
        },
        planned_session.athlete,
    )
    create_step(db, PlannedSessionStepCreate(**step_payload))
    return step_order + 1


def _infer_repeat_step_type(block: ImportBlock, nested_index: int) -> str:
    normalized_notes = (block.notes or "").strip().lower()
    normalized_intensity = _normalize_intensity(block.intensity)
    if "recup" in normalized_notes or "suave" in normalized_notes:
        return "recovery"
    if normalized_intensity == "hr" and nested_index > 1:
        return "recovery"
    if normalized_intensity in {"pace", "power"}:
        return "work"
    return "work" if nested_index == 1 else "recovery"


def _infer_simple_step_type(block: ImportBlock) -> str:
    normalized_notes = (block.notes or "").strip().lower()
    if "entrada" in normalized_notes or "warm" in normalized_notes:
        return "warmup"
    if "vuelta" in normalized_notes or "cool" in normalized_notes:
        return "cooldown"
    if "recup" in normalized_notes:
        return "recovery"
    return "steady"


def _infer_session_target_type(blocks: list[ImportBlock | ImportRepeat]) -> str | None:
    for block in blocks:
        if isinstance(block, ImportRepeat):
            if block.blocks:
                intensity = _normalize_intensity(block.blocks[0].intensity)
                if intensity in INTENSITY_TYPES:
                    return intensity
        else:
            intensity = _normalize_intensity(block.intensity)
            if intensity in INTENSITY_TYPES:
                return intensity
    return None


def _infer_session_target_zone(blocks: list[ImportBlock | ImportRepeat]) -> str | None:
    for block in blocks:
        if isinstance(block, ImportRepeat):
            if block.blocks:
                zone = _normalize_zone(block.blocks[0].zone)
                if zone and not _is_custom_zone(zone):
                    return zone
        else:
            zone = _normalize_zone(block.zone)
            if zone and not _is_custom_zone(zone):
                return zone
    return None


def _resolve_training_plan(
    db: Session,
    training_day_id: int | None,
    training_plan_id: int | None,
    base_date: date | None,
):
    if training_day_id:
        training_day = get_training_day(db, training_day_id)
        if training_day:
            return training_day.training_plan
    if training_plan_id:
        return get_training_plan(db, training_plan_id)
    if base_date:
        return None
    return None


def _resolve_training_day(
    db: Session,
    training_day_id: int | None,
    training_plan,
    day_date: date | None,
) -> TrainingDay:
    if training_day_id:
        existing = get_training_day(db, training_day_id)
        if existing:
            return existing
    if training_plan is None or day_date is None:
        raise ValueError("No se pudo resolver el dia para importar sesiones.")
    existing = get_training_day_by_plan_and_date(db, training_plan.id, day_date)
    if existing:
        return existing
    return create_training_day(
        db,
        TrainingDayCreate(
            training_plan_id=training_plan.id,
            athlete_id=training_plan.athlete_id,
            day_date=day_date,
            day_notes=None,
            day_type=None,
        ),
    )


def _resolve_session_date(group_date: date | None, session_date: date | None, base_date: date | None) -> date | None:
    return session_date or group_date or base_date


def _next_session_order(training_day_id: int, training_day: TrainingDay, cache: dict[int, int]) -> int:
    if training_day_id in cache:
        cache[training_day_id] += 1
        return cache[training_day_id]
    if not training_day.planned_sessions:
        cache[training_day_id] = 1
        return 1
    cache[training_day_id] = max(session.session_order for session in training_day.planned_sessions) + 1
    return cache[training_day_id]


def _load_zone_map(athlete, target_type: str) -> dict[str, dict[str, Any]]:
    if athlete is None:
        return {}
    zone_payload = load_zone_payload(
        getattr(athlete, f"{target_type}_zones_json", None)
    ).get("general") or []
    zone_by_name = {}
    for zone in zone_payload:
        name = str(zone.get("name") or "").strip().upper()
        if not name:
            continue
        zone_by_name[name] = {
            "min": zone.get("min"),
            "max": zone.get("max"),
        }
    return zone_by_name


def _resolve_block_pace_seconds(
    block: ImportBlock,
    intensity: str | None,
    zone: str | None,
    pace_zones: dict[str, dict[str, Any]],
    hr_zones: dict[str, dict[str, Any]],
) -> float | None:
    if _is_custom_zone(zone):
        if intensity == "pace":
            return _average_defined_numbers(_parse_pace_to_seconds(block.pace_min), _parse_pace_to_seconds(block.pace_max))
        return None
    if not zone:
        return None
    zone_key = zone.upper()
    if intensity == "pace":
        return _average_pace_seconds(pace_zones.get(zone_key))
    if intensity == "hr":
        return _average_pace_seconds(pace_zones.get(zone_key))
    return None


def _average_pace_seconds(zone_payload: dict[str, Any] | None) -> float | None:
    if not zone_payload:
        return None
    minimum = zone_payload.get("min")
    maximum = zone_payload.get("max")
    if minimum is None and maximum is None:
        return None
    if minimum is None:
        return float(maximum)
    if maximum is None:
        return float(minimum)
    return (float(minimum) + float(maximum)) / 2.0


def _normalize_unit(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"s", "sec"}:
        return "seg"
    return normalized


def _normalize_intensity(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in INTENSITY_TYPES else None


def _normalize_zone(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper()
    return normalized


def _is_custom_zone(value: str | None) -> bool:
    return bool(value and value.strip().lower() == "custom")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _parse_optional_int(value: str | None) -> int | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _parse_pace_to_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    match = PACE_PATTERN.fullmatch(value)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    if seconds > 59:
        return None
    return minutes * 60 + seconds


def _pace_to_label(value: int | None) -> str | None:
    if value is None:
        return None
    minutes = value // 60
    seconds = value % 60
    return f"{minutes}:{seconds:02d}"


def _average_defined_numbers(minimum: int | float | None, maximum: int | float | None) -> float | None:
    if minimum is None and maximum is None:
        return None
    if minimum is None:
        return float(maximum)
    if maximum is None:
        return float(minimum)
    return (float(minimum) + float(maximum)) / 2.0


def _to_seconds(unit: str, value: float) -> int:
    if unit == "seg":
        return int(round(value))
    if unit == "min":
        return int(round(value * 60))
    if unit == "h":
        return int(round(value * 3600))
    return int(round(value))


def _to_meters(unit: str, value: float) -> int:
    if unit == "km":
        return int(round(value * 1000))
    return int(round(value))


def _format_duration(value: int | None) -> str:
    if value is None:
        return "-"
    total_minutes = int(round(value / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d} h"
    return f"{minutes} min"


def _format_distance(value: int | None) -> str:
    if value is None:
        return "-"
    if value >= 1000:
        return f"{value / 1000:.2f} km"
    return f"{int(round(value))} m"


def _step_target_fields_from_block(block: ImportBlock, intensity: str | None, zone: str | None) -> dict[str, Any]:
    target_fields = {
        "target_hr_zone": None,
        "target_hr_min": None,
        "target_hr_max": None,
        "target_pace_zone": None,
        "target_pace_min_sec_km": None,
        "target_pace_max_sec_km": None,
        "target_power_zone": None,
        "target_power_min": None,
        "target_power_max": None,
        "target_rpe_zone": None,
    }
    if intensity == "hr":
        if _is_custom_zone(zone):
            target_fields["target_hr_min"] = _parse_optional_int(block.hr_min)
            target_fields["target_hr_max"] = _parse_optional_int(block.hr_max)
        else:
            target_fields["target_hr_zone"] = zone
    elif intensity == "pace":
        if _is_custom_zone(zone):
            target_fields["target_pace_min_sec_km"] = _parse_pace_to_seconds(block.pace_min)
            target_fields["target_pace_max_sec_km"] = _parse_pace_to_seconds(block.pace_max)
        else:
            target_fields["target_pace_zone"] = zone
    elif intensity == "power":
        if _is_custom_zone(zone):
            target_fields["target_power_min"] = _parse_optional_int(block.power_min)
            target_fields["target_power_max"] = _parse_optional_int(block.power_max)
        else:
            target_fields["target_power_zone"] = zone
    elif intensity == "rpe":
        if _is_custom_zone(zone):
            target_fields["target_rpe_zone"] = "custom"
        else:
            target_fields["target_rpe_zone"] = zone
    return target_fields


def _default_block_target_note(block: ImportBlock, intensity: str | None, zone: str | None) -> str | None:
    if not _is_custom_zone(zone):
        return zone
    description = _describe_block_target(block)
    return description.lower() if description else "custom"


def _describe_block_target(block: ImportBlock) -> str:
    intensity = _normalize_intensity(block.intensity)
    zone = _normalize_zone(block.zone)
    if not intensity:
        return zone or ""
    if not _is_custom_zone(zone):
        return " ".join(part for part in (_target_type_label(intensity), zone) if part)

    if intensity == "hr":
        return _custom_range_label(
            "FC personalizada",
            _parse_optional_int(block.hr_min),
            _parse_optional_int(block.hr_max),
            suffix="bpm",
        )
    if intensity == "pace":
        return _custom_range_label(
            "Ritmo personalizado",
            _pace_to_label(_parse_pace_to_seconds(block.pace_min)),
            _pace_to_label(_parse_pace_to_seconds(block.pace_max)),
            suffix="min/km",
        )
    if intensity == "power":
        return _custom_range_label(
            "Potencia personalizada",
            _parse_optional_int(block.power_min),
            _parse_optional_int(block.power_max),
            suffix="W",
        )
    if intensity == "rpe":
        return _custom_range_label(
            "RPE personalizado",
            _parse_optional_int(block.rpe_min),
            _parse_optional_int(block.rpe_max),
            suffix="RPE",
        )
    return "custom"


def _custom_range_label(label: str, minimum: Any, maximum: Any, *, suffix: str) -> str:
    min_label = str(minimum) if minimum is not None else "-"
    max_label = str(maximum) if maximum is not None else "-"
    return f"{label} [{min_label}-{max_label} {suffix}]"


def _target_type_label(value: str | None) -> str | None:
    mapping = {
        "hr": "FC",
        "pace": "Ritmo",
        "power": "Potencia",
        "rpe": "RPE",
    }
    if not value:
        return None
    return mapping.get(value, value)


def _format_errors(errors) -> list[dict[str, Any]]:
    return [{"line": error.line, "message": error.message} for error in errors]


def _build_import_redirect_url(
    *,
    training_day_id: int | None,
    training_plan_id: int | None,
    base_date: date | None,
    return_to: str | None,
    return_month: str | None,
    return_selected_date: str | None,
) -> str | None:
    normalized_return_to = (return_to or "").strip().lower()
    if training_day_id and normalized_return_to == "day":
        return f"/training_days/{training_day_id}?ui_status=Sesiones%20importadas"
    if training_plan_id and normalized_return_to == "calendar":
        month = return_month or (base_date.strftime("%Y-%m") if base_date else "")
        selected_day = return_selected_date or (base_date.isoformat() if base_date else "")
        return f"/training_plans/{training_plan_id}/calendar?month={month}&selected_date={selected_day}&status=Sesiones%20importadas"
    if training_plan_id and normalized_return_to == "plan":
        return f"/training_plans/{training_plan_id}#training-day"
    return None
