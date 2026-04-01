from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.services.planning.presentation import (
    build_session_display_blocks,
    build_session_display_blocks_for_session,
    describe_session_structure,
    describe_session_structure_short,
    derive_session_metrics,
    format_duration_human_from_minutes,
    format_duration_human_from_seconds,
)
from app.services.athlete_zone_service import DEFAULT_RPE_LABELS, ZONE_NAMES
from app.services.garmin.profile_sync import load_zone_payload
from app.ui.catalogs import (
    ANALYSIS_STATUS_LABELS,
    DAY_TYPE_LABELS,
    DAY_TYPE_OPTIONS,
    GROUP_TYPE_LABELS,
    GROUP_TYPE_OPTIONS,
    MATCH_METHOD_LABELS,
    INTENSITY_TARGET_LABELS,
    INTENSITY_TARGET_OPTIONS,
    RPE_ZONE_LABELS,
    RPE_ZONE_OPTIONS,
    SESSION_TYPE_LABELS,
    SESSION_TYPE_OPTIONS,
    SPORT_LABELS,
    SPORT_OPTIONS,
    STEP_TYPE_LABELS,
    STEP_TYPE_OPTIONS,
    VARIANT_LABELS,
    VARIANT_OPTIONS,
    ZONE_OPTIONS,
    label_for,
)


def _format_duration_minutes_hhmm(value: int | None) -> str:
    if value is None:
        return ""
    hours, minutes = divmod(int(value), 60)
    return f"{hours}:{minutes:02d}"


def _format_duration_seconds_hhmm(value: int | None) -> str:
    if value is None:
        return ""
    total_minutes = int(round(value / 60))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}"


def _distance_form_value(value_meters: float | None) -> float | None:
    if value_meters is None:
        return None
    if value_meters >= 1000:
        return round(value_meters / 1000, 2)
    return round(value_meters, 0)


def _distance_form_unit(value_meters: float | None) -> str:
    if value_meters is None:
        return "km"
    return "km" if value_meters >= 1000 else "m"


def _distance_form_value_km(value_km: float | None) -> float | None:
    if value_km is None:
        return None
    if value_km >= 1:
        return round(value_km, 2)
    return round(value_km * 1000, 0)


def _distance_form_unit_km(value_km: float | None) -> str:
    if value_km is None:
        return "km"
    return "km" if value_km >= 1 else "m"


def _format_pace_mmss(value: int | None) -> str:
    if value is None:
        return ""
    minutes, seconds = divmod(int(value), 60)
    return f"{minutes}:{seconds:02d}"


def _distance_label_meters(value_meters: float | None) -> str:
    if value_meters is None:
        return "-"
    if value_meters >= 1000:
        return f"{value_meters / 1000:.2f} km"
    return f"{int(round(value_meters))} m"


def _distance_label_km(value_km: float | None) -> str:
    if value_km is None:
        return "-"
    if value_km >= 1:
        return f"{value_km:.2f} km"
    return f"{int(round(value_km * 1000))} m"


def _zone_range_label(
    minimum: int | None,
    maximum: int | None,
    *,
    suffix: str = "",
    formatter=None,
) -> str:
    if minimum is None and maximum is None:
        return ""
    render = formatter or (lambda value: str(value))
    if minimum is not None and maximum is not None:
        return f"{render(minimum)} a {render(maximum)}{suffix}"
    if minimum is not None:
        return f"desde {render(minimum)}{suffix}"
    return f"hasta {render(maximum)}{suffix}"


def _athlete_target_zone_options(athlete: object | None, target_type: str) -> list[dict[str, str]]:
    if athlete is None:
        if target_type == "rpe":
            return [{"value": name, "label": f"{name} · {DEFAULT_RPE_LABELS.get(name, name)}"} for name in ZONE_NAMES]
        return [{"value": name, "label": name} for name in ZONE_NAMES]

    zone_payload = {
        "hr": load_zone_payload(getattr(athlete, "hr_zones_json", None)).get("general"),
        "pace": load_zone_payload(getattr(athlete, "pace_zones_json", None)).get("general"),
        "power": load_zone_payload(getattr(athlete, "power_zones_json", None)).get("general"),
        "rpe": load_zone_payload(getattr(athlete, "rpe_zones_json", None)).get("general"),
    }.get(target_type) or []
    zone_by_name = {str(zone.get("name") or "").strip(): zone for zone in zone_payload}

    options: list[dict[str, str]] = []
    for zone_name in ZONE_NAMES:
        zone = zone_by_name.get(zone_name, {})
        if target_type == "hr":
            detail = _zone_range_label(zone.get("min"), zone.get("max"), suffix=" bpm")
        elif target_type == "pace":
            detail = _zone_range_label(zone.get("min"), zone.get("max"), suffix=" min/km", formatter=_format_pace_mmss)
        elif target_type == "power":
            detail = _zone_range_label(zone.get("min"), zone.get("max"), suffix=" w")
        else:
            detail = str(zone.get("label") or DEFAULT_RPE_LABELS.get(zone_name, zone_name)).strip()
        options.append(
            {
                "value": zone_name,
                "label": f"{zone_name} · {detail}" if detail else zone_name,
            }
        )
    return options


def _athlete_target_zone_map(athlete: object | None, target_type: str) -> dict[str, dict[str, object]]:
    if athlete is None:
        if target_type == "rpe":
            return {
                zone_name: {"name": zone_name, "label": DEFAULT_RPE_LABELS.get(zone_name, zone_name)}
                for zone_name in ZONE_NAMES
            }
        return {zone_name: {"name": zone_name, "min": None, "max": None} for zone_name in ZONE_NAMES}

    zone_payload = {
        "hr": load_zone_payload(getattr(athlete, "hr_zones_json", None)).get("general"),
        "pace": load_zone_payload(getattr(athlete, "pace_zones_json", None)).get("general"),
        "power": load_zone_payload(getattr(athlete, "power_zones_json", None)).get("general"),
        "rpe": load_zone_payload(getattr(athlete, "rpe_zones_json", None)).get("general"),
    }.get(target_type) or []
    zone_by_name = {str(zone.get("name") or "").strip(): zone for zone in zone_payload}

    mapped: dict[str, dict[str, object]] = {}
    for zone_name in ZONE_NAMES:
        zone = zone_by_name.get(zone_name, {})
        mapped[zone_name] = {
            "name": zone_name,
            "min": zone.get("min"),
            "max": zone.get("max"),
            "label": str(zone.get("label") or DEFAULT_RPE_LABELS.get(zone_name, zone_name)).strip(),
        }
    return mapped


def _session_group_summary(session_group: object) -> dict[str, object]:
    sessions = getattr(session_group, "planned_sessions", []) or []
    total_duration_sec = 0
    has_duration = False
    total_distance_m = 0
    has_distance = False

    for planned_session in sessions:
        metrics = derive_session_metrics(planned_session)
        if metrics.duration_sec is not None:
            total_duration_sec += metrics.duration_sec
            has_duration = True
        if metrics.distance_m is not None:
            total_distance_m += metrics.distance_m
            has_distance = True

    return {
        "session_count": len(sessions),
        "duration_label": format_duration_human_from_seconds(total_duration_sec) if has_duration else None,
        "distance_label": _distance_label_meters(total_distance_m) if has_distance else None,
    }


def build_templates(base_path: Path) -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(base_path / "templates"))
    templates.env.globals.update(
        sport_options=SPORT_OPTIONS,
        variant_options=VARIANT_OPTIONS,
        session_type_options=SESSION_TYPE_OPTIONS,
        step_type_options=STEP_TYPE_OPTIONS,
        group_type_options=GROUP_TYPE_OPTIONS,
        day_type_options=DAY_TYPE_OPTIONS,
        zone_options=ZONE_OPTIONS,
        intensity_target_options=INTENSITY_TARGET_OPTIONS,
        rpe_zone_options=RPE_ZONE_OPTIONS,
        sport_label=lambda value: label_for(SPORT_LABELS, value),
        variant_label=lambda value: label_for(VARIANT_LABELS, value),
        session_type_label=lambda value: label_for(SESSION_TYPE_LABELS, value),
        step_type_label=lambda value: label_for(STEP_TYPE_LABELS, value),
        group_type_label=lambda value: label_for(GROUP_TYPE_LABELS, value),
        day_type_label=lambda value: label_for(DAY_TYPE_LABELS, value),
        match_method_label=lambda value: label_for(MATCH_METHOD_LABELS, value),
        analysis_status_label=lambda value: label_for(ANALYSIS_STATUS_LABELS, value),
        intensity_target_label=lambda value: label_for(INTENSITY_TARGET_LABELS, value),
        rpe_zone_label=lambda value: label_for(RPE_ZONE_LABELS, value),
        duration_minutes_hhmm=_format_duration_minutes_hhmm,
        duration_seconds_hhmm=_format_duration_seconds_hhmm,
        duration_minutes_human=format_duration_human_from_minutes,
        duration_seconds_human=format_duration_human_from_seconds,
        distance_form_value=_distance_form_value,
        distance_form_unit=_distance_form_unit,
        distance_form_value_km=_distance_form_value_km,
        distance_form_unit_km=_distance_form_unit_km,
        pace_mmss=_format_pace_mmss,
        distance_label_meters=_distance_label_meters,
        distance_label_km=_distance_label_km,
        athlete_target_zone_options=_athlete_target_zone_options,
        athlete_target_zone_map=_athlete_target_zone_map,
        session_group_summary=_session_group_summary,
        session_display_blocks=build_session_display_blocks,
        session_display_blocks_for_session=build_session_display_blocks_for_session,
        session_structure_summary=describe_session_structure,
        session_structure_summary_short=describe_session_structure_short,
        derive_session_metrics=derive_session_metrics,
    )
    return templates
