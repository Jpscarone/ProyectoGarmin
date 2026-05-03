from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from app.services.garmin.profile_sync import load_zone_payload


@dataclass(frozen=True)
class SessionDisplaySimpleStep:
    kind: Literal["simple"]
    step_order: int
    step_type: str
    repeat_count: int | None
    duration_sec: int | None
    distance_m: int | None
    target_type: str | None
    target_hr_zone: str | None
    target_hr_min: int | None
    target_hr_max: int | None
    target_power_zone: str | None
    target_power_min: int | None
    target_power_max: int | None
    target_pace_zone: str | None
    target_pace_min_sec_km: int | None
    target_pace_max_sec_km: int | None
    target_rpe_zone: str | None
    target_cadence_min: int | None
    target_cadence_max: int | None
    target_notes: str | None
    source_step_id: int | None


@dataclass(frozen=True)
class SessionDisplayRepeatBlock:
    kind: Literal["repeat"]
    repeat_count: int
    step_order: int
    steps: list[SessionDisplaySimpleStep]


SessionDisplayBlock = SessionDisplaySimpleStep | SessionDisplayRepeatBlock


@dataclass(frozen=True)
class SessionDerivedMetrics:
    duration_sec: int | None
    distance_m: int | None
    duration_is_estimated: bool
    distance_is_estimated: bool
    title: str | None


def build_session_display_blocks(
    planned_session_steps: list[object],
    *,
    fallback_target_type: str | None = None,
) -> list[SessionDisplayBlock]:
    blocks: list[SessionDisplayBlock] = []
    current_repeat_steps: list[SessionDisplaySimpleStep] = []
    current_repeat_count: int | None = None

    for raw_step in planned_session_steps:
        inferred_target_type = getattr(raw_step, "target_type", None)
        if inferred_target_type is None and not any(
            [
                getattr(raw_step, "target_hr_zone", None),
                getattr(raw_step, "target_pace_zone", None),
                getattr(raw_step, "target_power_zone", None),
                getattr(raw_step, "target_rpe_zone", None),
            ]
        ):
            inferred_target_type = fallback_target_type

        display_step = SessionDisplaySimpleStep(
            kind="simple",
            step_order=raw_step.step_order,
            step_type=raw_step.step_type,
            repeat_count=raw_step.repeat_count,
            duration_sec=raw_step.duration_sec,
            distance_m=raw_step.distance_m,
            target_type=inferred_target_type,
            target_hr_zone=getattr(raw_step, "target_hr_zone", None),
            target_hr_min=raw_step.target_hr_min,
            target_hr_max=raw_step.target_hr_max,
            target_power_zone=getattr(raw_step, "target_power_zone", None),
            target_power_min=raw_step.target_power_min,
            target_power_max=raw_step.target_power_max,
            target_pace_zone=getattr(raw_step, "target_pace_zone", None),
            target_pace_min_sec_km=raw_step.target_pace_min_sec_km,
            target_pace_max_sec_km=raw_step.target_pace_max_sec_km,
            target_rpe_zone=getattr(raw_step, "target_rpe_zone", None),
            target_cadence_min=raw_step.target_cadence_min,
            target_cadence_max=raw_step.target_cadence_max,
            target_notes=raw_step.target_notes,
            source_step_id=raw_step.id,
        )

        if raw_step.repeat_count and raw_step.repeat_count > 1:
            if current_repeat_count == raw_step.repeat_count and not _starts_new_repeat_group(current_repeat_steps, display_step):
                current_repeat_steps.append(display_step)
            else:
                _flush_repeat_group(blocks, current_repeat_count, current_repeat_steps)
                current_repeat_count = raw_step.repeat_count
                current_repeat_steps = [display_step]
            continue

        _flush_repeat_group(blocks, current_repeat_count, current_repeat_steps)
        current_repeat_count = None
        current_repeat_steps = []
        blocks.append(display_step)

    _flush_repeat_group(blocks, current_repeat_count, current_repeat_steps)
    return blocks


def build_session_display_blocks_for_session(planned_session: object) -> list[SessionDisplayBlock]:
    session_steps = getattr(planned_session, "planned_session_steps", []) or []
    if session_steps:
        return build_session_display_blocks(session_steps, fallback_target_type=getattr(planned_session, "target_type", None))

    duration_sec = getattr(planned_session, "expected_duration_min", None)
    distance_km = getattr(planned_session, "expected_distance_km", None)
    if duration_sec is None and distance_km is None and not getattr(planned_session, "target_notes", None):
        return []

    return [
        SessionDisplaySimpleStep(
            kind="simple",
            step_order=1,
            step_type=_session_type_to_default_step_type(getattr(planned_session, "session_type", None)),
            repeat_count=None,
            duration_sec=duration_sec * 60 if duration_sec is not None else None,
            distance_m=int(round(distance_km * 1000)) if distance_km is not None else None,
            target_type=getattr(planned_session, "target_type", None),
            target_hr_zone=getattr(planned_session, "target_hr_zone", None),
            target_hr_min=None,
            target_hr_max=None,
            target_power_zone=getattr(planned_session, "target_power_zone", None),
            target_power_min=None,
            target_power_max=None,
            target_pace_zone=getattr(planned_session, "target_pace_zone", None),
            target_pace_min_sec_km=None,
            target_pace_max_sec_km=None,
            target_rpe_zone=getattr(planned_session, "target_rpe_zone", None),
            target_cadence_min=None,
            target_cadence_max=None,
            target_notes=getattr(planned_session, "target_notes", None),
            source_step_id=None,
        )
    ]


def derive_session_metrics(planned_session: object) -> SessionDerivedMetrics:
    display_blocks = build_session_display_blocks_for_session(planned_session)
    if getattr(planned_session, "planned_session_steps", None):
        duration_sec = _display_blocks_duration_sec(display_blocks)
        distance_m = _display_blocks_distance_m(display_blocks)
        return SessionDerivedMetrics(
            duration_sec=duration_sec,
            distance_m=distance_m,
            duration_is_estimated=False,
            distance_is_estimated=False,
            title=_display_blocks_title(planned_session, display_blocks),
        )

    duration_min = getattr(planned_session, "expected_duration_min", None)
    distance_km = getattr(planned_session, "expected_distance_km", None)
    return SessionDerivedMetrics(
        duration_sec=duration_min * 60 if duration_min is not None else None,
        distance_m=int(round(distance_km * 1000)) if distance_km is not None else None,
        duration_is_estimated=False,
        distance_is_estimated=False,
        title=getattr(planned_session, "name", None),
    )


def describe_session_structure(planned_session: object) -> str | None:
    display_blocks = build_session_display_blocks_for_session(planned_session)
    if not display_blocks:
        return None

    parts = [_describe_display_block(block) for block in display_blocks]
    parts = [part for part in parts if part]
    if not parts:
        return None
    return " + ".join(parts)


def describe_session_structure_short(planned_session: object) -> str | None:
    display_blocks = build_session_display_blocks_for_session(planned_session)
    if not display_blocks:
        return None

    parts = [_describe_display_block_short(block) for block in display_blocks]
    parts = [part for part in parts if part]
    if not parts:
        return None
    return " + ".join(parts)


def build_session_summary(planned_session: object) -> str | None:
    display_blocks = build_session_display_blocks_for_session(planned_session)
    if not display_blocks:
        return None

    parts = [_summary_display_block(block) for block in display_blocks]
    parts = [part for part in parts if part]
    if not parts:
        return None

    sport_label = _summary_sport_label(getattr(planned_session, "sport_type", None))
    summary = " + ".join(parts)
    return f"{sport_label} {summary}".strip() if sport_label else summary


def build_session_summary_with_ranges(planned_session: object, *, html: bool = False) -> str | None:
    display_blocks = build_session_display_blocks_for_session(planned_session)
    if not display_blocks:
        return None

    zone_lookup = _build_zone_lookup(getattr(planned_session, "athlete", None))
    parts = [_summary_display_block_with_ranges(block, zone_lookup, html=html) for block in display_blocks]
    parts = [part for part in parts if part]
    if not parts:
        return None

    sport_label = _summary_sport_label(getattr(planned_session, "sport_type", None))
    summary = " + ".join(parts)
    return f"{sport_label} {summary}".strip() if sport_label else summary


def build_session_compact_outline(planned_session: object) -> str | None:
    display_blocks = build_session_display_blocks_for_session(planned_session)
    if not display_blocks:
        return None

    parts = [_compact_block_measurement(block) for block in display_blocks]
    parts = [part for part in parts if part]
    if not parts:
        return None
    return " + ".join(parts)


def _flush_repeat_group(
    blocks: list[SessionDisplayBlock],
    repeat_count: int | None,
    repeat_steps: list[SessionDisplaySimpleStep],
) -> None:
    if not repeat_steps or not repeat_count:
        return
    blocks.append(
        SessionDisplayRepeatBlock(
            kind="repeat",
            repeat_count=repeat_count,
            step_order=repeat_steps[0].step_order,
            steps=list(repeat_steps),
        )
    )


def _starts_new_repeat_group(
    repeat_steps: list[SessionDisplaySimpleStep],
    candidate_step: SessionDisplaySimpleStep,
) -> bool:
    if not repeat_steps:
        return False
    has_recovery = any(step.step_type == "recovery" for step in repeat_steps)
    candidate_is_recovery = candidate_step.step_type == "recovery"
    if has_recovery and not candidate_is_recovery:
        return True
    return False


def format_duration_human_from_seconds(value: int | None) -> str:
    if value is None:
        return ""
    if value < 60:
        return f"{int(value)}s"
    if value < 3600:
        if value % 60 == 0:
            return f"{int(value // 60)}min"
        minutes = value // 60
        seconds = value % 60
        return f"{int(minutes)}:{int(seconds):02d}"
    hours = value // 3600
    minutes = (value % 3600) // 60
    if minutes == 0:
        return f"{int(hours)}h"
    return f"{int(hours)}h {int(minutes)}min"


def format_duration_human_from_minutes(value: int | None) -> str:
    if value is None:
        return ""
    total_seconds = int(value) * 60
    return format_duration_human_from_seconds(total_seconds)


def _display_blocks_duration_sec(blocks: list[SessionDisplayBlock]) -> int | None:
    total_seconds = 0
    has_primary_duration = False
    for block in blocks:
        if isinstance(block, SessionDisplayRepeatBlock):
            nested_total = 0
            for step in block.steps:
                if step.duration_sec is None:
                    return None
                nested_total += step.duration_sec
                if step.step_type != "recovery":
                    has_primary_duration = True
            total_seconds += nested_total * block.repeat_count
            continue

        if block.duration_sec is None:
            return None
        total_seconds += block.duration_sec
        if block.step_type != "recovery":
            has_primary_duration = True

    if total_seconds == 0 or not has_primary_duration:
        return None
    return total_seconds


def _display_blocks_distance_m(blocks: list[SessionDisplayBlock]) -> int | None:
    total_meters = 0
    has_distance = False
    for block in blocks:
        if isinstance(block, SessionDisplayRepeatBlock):
            nested_distance = 0
            nested_has_distance = False
            for step in block.steps:
                if step.distance_m is None:
                    continue
                nested_distance += step.distance_m
                nested_has_distance = True
            if nested_has_distance:
                total_meters += nested_distance * block.repeat_count
                has_distance = True
            continue

        if block.distance_m is None:
            continue
        total_meters += block.distance_m
        has_distance = True

    if not has_distance:
        return None
    return total_meters


def _display_blocks_title(planned_session: object, blocks: list[SessionDisplayBlock]) -> str | None:
    sport = getattr(planned_session, "sport_type", None)
    sport_label = {
        "cycling": "Bici",
        "mtb": "MTB",
        "running": "Running",
        "trail_running": "Trail",
        "swimming": "Natacion",
        "multisport": "Multideporte",
    }.get(sport, "")

    priority_blocks = [block for block in blocks if _block_is_title_priority(block)]
    source_blocks = priority_blocks or blocks
    title_fragments = [_display_block_title_fragment(block) for block in source_blocks]
    title_fragments = [fragment for fragment in title_fragments if fragment]
    if title_fragments:
        visible_fragments = title_fragments[:3]
        title = " + ".join(visible_fragments)
        if len(title_fragments) > 3:
            title += " + ..."
        return " ".join(part for part in (sport_label, title) if part).strip()

    return getattr(planned_session, "name", None)


def _display_step_measurement(step: SessionDisplaySimpleStep) -> str:
    if step.distance_m is not None:
        if step.distance_m >= 1000 and step.distance_m % 1000 == 0:
            return f"{int(step.distance_m / 1000)}km"
        if step.distance_m >= 1000:
            return f"{step.distance_m / 1000:.1f}km"
        return f"{step.distance_m}m"

    if step.duration_sec is None:
        return ""
    if step.duration_sec < 60:
        return f"{int(step.duration_sec)}s"
    if step.duration_sec < 3600:
        if step.duration_sec % 60 == 0:
            return f"{int(step.duration_sec // 60)}min"
        minutes = step.duration_sec // 60
        seconds = step.duration_sec % 60
        return f"{int(minutes)}:{int(seconds):02d}"
    hours = step.duration_sec // 3600
    minutes = (step.duration_sec % 3600) // 60
    if minutes == 0:
        return f"{int(hours)}h"
    return f"{int(hours)}h {int(minutes)}min"


def _display_repeat_fragment(block: SessionDisplayRepeatBlock) -> str:
    work_step = next((step for step in block.steps if step.step_type == "work"), block.steps[0])
    work_fragment = _display_step_measurement(work_step)

    recovery_step = next(
        (
            step
            for step in block.steps
            if step.step_type == "recovery" and (step.duration_sec is not None or step.distance_m is not None)
        ),
        None,
    )
    if recovery_step is None:
        return f"{block.repeat_count}x{work_fragment}"

    recovery_fragment = _display_step_measurement(recovery_step)
    return f"{block.repeat_count}x({work_fragment} + {recovery_fragment})"


def _display_repeat_fragment_short(block: SessionDisplayRepeatBlock) -> str:
    work_step = next((step for step in block.steps if step.step_type == "work"), block.steps[0])
    work_fragment = _display_step_measurement(work_step)

    recovery_step = next(
        (
            step
            for step in block.steps
            if step.step_type == "recovery" and (step.duration_sec is not None or step.distance_m is not None)
        ),
        None,
    )
    if recovery_step is None:
        return f"{block.repeat_count}x{work_fragment}"

    recovery_fragment = _display_step_measurement(recovery_step)
    return f"{block.repeat_count}x({work_fragment}+{recovery_fragment})"


def _display_repeat_intensity(block: SessionDisplayRepeatBlock) -> str:
    work_step = next((step for step in block.steps if step.step_type == "work"), block.steps[0])
    return _display_step_intensity(work_step)


def _display_block_title_fragment(block: SessionDisplayBlock) -> str:
    if isinstance(block, SessionDisplayRepeatBlock):
        repeat_fragment = _display_repeat_fragment_short(block)
        intensity = _display_repeat_intensity(block)
        return " ".join(part for part in (repeat_fragment, intensity) if part).strip()

    measurement = _display_step_measurement(block)
    intensity = _display_step_intensity(block)
    return " ".join(part for part in (measurement, intensity) if part).strip()


def _describe_display_block(block: SessionDisplayBlock) -> str:
    if isinstance(block, SessionDisplayRepeatBlock):
        nested = [_describe_simple_step(step) for step in block.steps]
        nested = [part for part in nested if part]
        if not nested:
            return ""
        return f"{block.repeat_count}x({ ' + '.join(nested) })"
    return _describe_simple_step(block)


def _describe_display_block_short(block: SessionDisplayBlock) -> str:
    if isinstance(block, SessionDisplayRepeatBlock):
        work_step = next((step for step in block.steps if step.step_type == "work"), block.steps[0])
        recovery_step = next(
            (
                step
                for step in block.steps
                if step.step_type == "recovery" and (step.duration_sec is not None or step.distance_m is not None)
            ),
            None,
        )
        work_fragment = _display_step_measurement(work_step)
        work_intensity = (work_step.target_notes or "").strip()
        if recovery_step is None:
            return " ".join(part for part in (f"{block.repeat_count}x{work_fragment}", work_intensity) if part)

        recovery_fragment = _display_step_measurement(recovery_step)
        return " ".join(
            part for part in (f"{block.repeat_count}x({work_fragment}+{recovery_fragment})", work_intensity) if part
        )
    return _describe_simple_step(block)


def _describe_simple_step(step: SessionDisplaySimpleStep) -> str:
    measurement = _display_step_measurement(step)
    label = _display_step_intensity(step)
    if measurement and label:
        return f"{measurement} {label}"
    return measurement or label


def _summary_display_block(block: SessionDisplayBlock) -> str:
    if isinstance(block, SessionDisplayRepeatBlock):
        nested = [_summary_simple_step(step) for step in block.steps]
        nested = [part for part in nested if part]
        if not nested:
            return ""
        return f"{block.repeat_count}x({ ' + '.join(nested) })"
    return _summary_simple_step(block)


def _compact_block_measurement(block: SessionDisplayBlock) -> str:
    if isinstance(block, SessionDisplayRepeatBlock):
        nested = [_display_step_measurement(step) for step in block.steps]
        nested = [part for part in nested if part]
        if not nested:
            return ""
        inner = " + ".join(nested)
        return f"{block.repeat_count} x ({inner})"
    return _display_step_measurement(block)


def _summary_display_block_with_ranges(
    block: SessionDisplayBlock,
    zone_lookup: dict[str, dict[str, int | None]],
    *,
    html: bool,
) -> str:
    if isinstance(block, SessionDisplayRepeatBlock):
        nested = [_summary_simple_step_with_ranges(step, zone_lookup, html=html) for step in block.steps]
        nested = [part for part in nested if part]
        if not nested:
            return ""
        return f"{block.repeat_count}x({ ' + '.join(nested) })"
    return _summary_simple_step_with_ranges(block, zone_lookup, html=html)


def _summary_simple_step(step: SessionDisplaySimpleStep) -> str:
    measurement = _display_step_measurement(step)
    zone_label = _summary_step_zone(step)
    if measurement and zone_label:
        return f"{measurement} {zone_label}"
    return measurement or zone_label


def _summary_simple_step_with_ranges(
    step: SessionDisplaySimpleStep,
    zone_lookup: dict[str, dict[str, int | None]],
    *,
    html: bool,
) -> str:
    measurement = _display_step_measurement(step)
    zone_label, is_recovery = _summary_step_zone_with_range(step, zone_lookup)
    if not measurement and not zone_label:
        return ""

    if html and zone_label:
        classes = "session-criteria"
        if is_recovery:
            classes = f"{classes} recovery-step"
        zone_label = f'<span class="{classes}">{zone_label}</span>'

    if measurement and zone_label:
        return f"{measurement} {zone_label}"
    return measurement or zone_label or ""


def _summary_step_zone(step: SessionDisplaySimpleStep) -> str | None:
    zone_label = (
        _normalize_zone_label(step.target_pace_zone)
        or _normalize_zone_label(step.target_hr_zone)
        or _normalize_zone_label(step.target_power_zone)
        or _normalize_zone_label(step.target_rpe_zone)
        or _normalize_zone_label(step.target_notes)
    )
    if not zone_label:
        target_type = _resolve_target_type(step)
        if target_type in {"hr", "pace", "power"} and _step_has_explicit_range(step, target_type):
            return _custom_target_label(target_type, include_range=False)
        return None
    prefix = _target_type_prefix(_resolve_target_type(step))
    return f"{prefix} {zone_label.upper()}" if prefix else zone_label.upper()


def _summary_step_zone_with_range(
    step: SessionDisplaySimpleStep,
    zone_lookup: dict[str, dict[str, int | None]],
) -> tuple[str | None, bool]:
    zone_label = (
        _normalize_zone_label(step.target_pace_zone)
        or _normalize_zone_label(step.target_hr_zone)
        or _normalize_zone_label(step.target_power_zone)
        or _normalize_zone_label(step.target_rpe_zone)
        or _normalize_zone_label(step.target_notes)
    )
    if not zone_label:
        target_type = _resolve_target_type(step)
        if target_type in {"hr", "pace", "power", "rpe"} and _step_has_explicit_range(step, target_type):
            prefix = _custom_target_label(target_type, include_range=False)
            range_label = _step_range_label(step, target_type, "", zone_lookup)
            if not prefix:
                return None, False
            label = f"{prefix}"
            if range_label:
                label = f"{label} [{range_label}]"
            return label, False
        return None, False

    target_type = _resolve_target_type(step)
    prefix = _target_type_prefix(target_type)
    zone_key = zone_label.upper()
    range_label = _step_range_label(step, target_type, zone_key, zone_lookup)
    label = f"{prefix} {zone_key}" if prefix else zone_key
    if range_label:
        label = f"{label} [{range_label}]"
    return label, zone_label.lower() in {"z1", "z2"}


def _step_has_explicit_range(step: SessionDisplaySimpleStep, target_type: str) -> bool:
    if target_type == "pace":
        return step.target_pace_min_sec_km is not None or step.target_pace_max_sec_km is not None
    if target_type == "hr":
        return step.target_hr_min is not None or step.target_hr_max is not None
    if target_type == "power":
        return step.target_power_min is not None or step.target_power_max is not None
    if target_type == "rpe":
        return _rpe_range_from_notes(step.target_notes) is not None
    return False


def _normalize_zone_label(raw: str | None) -> str | None:
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    match = re.search(r"\bZ([1-5])\b", value.upper())
    if match:
        return f"z{match.group(1)}"
    return None


def _build_zone_lookup(athlete: object | None) -> dict[str, dict[str, int | None]]:
    if athlete is None:
        return {}

    lookup: dict[str, dict[str, int | None]] = {}
    for target_type in ("hr", "pace", "power", "rpe"):
        raw = getattr(athlete, f"{target_type}_zones_json", None)
        zone_payload = load_zone_payload(raw).get("general") or []
        for zone in zone_payload:
            name = str(zone.get("name") or "").strip().upper()
            if not name:
                continue
            lookup[f"{target_type}:{name}"] = {
                "min": zone.get("min"),
                "max": zone.get("max"),
            }
    return lookup


def _resolve_target_type(step: SessionDisplaySimpleStep) -> str | None:
    if step.target_type:
        return str(step.target_type).strip().lower()
    if step.target_hr_zone:
        return "hr"
    if step.target_pace_zone:
        return "pace"
    if step.target_power_zone:
        return "power"
    if step.target_rpe_zone:
        return "rpe"
    hint = (step.target_notes or "").lower()
    if "ritmo" in hint or "pace" in hint:
        return "pace"
    if "fc" in hint or "cardio" in hint:
        return "hr"
    if "potencia" in hint or "power" in hint:
        return "power"
    if "rpe" in hint:
        return "rpe"
    if step.distance_m is not None and step.duration_sec is None:
        return "pace"
    if step.duration_sec is not None and step.distance_m is None:
        return "hr"
    return None


def _target_type_prefix(target_type: str | None) -> str:
    mapping = {
        "hr": "FC",
        "pace": "Ritmo",
        "power": "Potencia",
        "rpe": "RPE",
    }
    if not target_type:
        return ""
    return mapping.get(target_type, "")


def _format_zone_range_label(target_type: str | None, zone_range: dict[str, int | None] | None) -> str | None:
    if not zone_range:
        return None
    minimum = zone_range.get("min")
    maximum = zone_range.get("max")
    if minimum is None and maximum is None:
        return None
    if target_type == "pace":
        return _format_pace_range(minimum, maximum)
    if target_type in {"hr", "power", "rpe"}:
        return _format_numeric_range(minimum, maximum)
    return _format_numeric_range(minimum, maximum)


def _format_numeric_range(minimum: int | None, maximum: int | None) -> str | None:
    if minimum is None and maximum is None:
        return None
    if minimum is None:
        return f"hasta {maximum}"
    if maximum is None:
        return f"{minimum}+"
    return f"{minimum}-{maximum}"


def _format_pace_range(minimum: int | None, maximum: int | None) -> str | None:
    if minimum is None and maximum is None:
        return None
    if minimum is None:
        return f"hasta {_pace_label(maximum)}"
    if maximum is None:
        return f"{_pace_label(minimum)}+"
    return f"{_pace_label(minimum)}-{_pace_label(maximum)}"


def _pace_label(minimum: int | None) -> str:
    if minimum is None:
        return "-"
    minutes, seconds = divmod(int(minimum), 60)
    return f"{minutes}:{seconds:02d}"


def _step_range_label(
    step: SessionDisplaySimpleStep,
    target_type: str | None,
    zone_key: str,
    zone_lookup: dict[str, dict[str, int | None]],
) -> str | None:
    if target_type == "hr":
        if step.target_hr_min is not None or step.target_hr_max is not None:
            return _format_numeric_range(step.target_hr_min, step.target_hr_max)
        return _format_zone_range_label(target_type, zone_lookup.get(f"{target_type}:{zone_key}"))
    if target_type == "pace":
        if step.target_pace_min_sec_km is not None or step.target_pace_max_sec_km is not None:
            return _format_pace_range(step.target_pace_min_sec_km, step.target_pace_max_sec_km)
        return _format_zone_range_label(target_type, zone_lookup.get(f"{target_type}:{zone_key}"))
    if target_type == "power":
        if step.target_power_min is not None or step.target_power_max is not None:
            return _format_numeric_range(step.target_power_min, step.target_power_max)
        return _format_zone_range_label(target_type, zone_lookup.get(f"{target_type}:{zone_key}"))
    if target_type == "rpe":
        rpe_range = _rpe_range_from_notes(step.target_notes)
        if rpe_range:
            return _format_numeric_range(rpe_range[0], rpe_range[1])
        return _format_zone_range_label(target_type, zone_lookup.get(f"{target_type}:{zone_key}"))
    return None


def _summary_sport_label(raw: str | None) -> str:
    if not raw:
        return ""
    mapping = {
        "running": "Running",
        "cycling": "Cycling",
        "swimming": "Swimming",
        "strength": "Strength",
        "walking": "Walking",
        "mtb": "MTB",
        "trail_running": "Trail",
        "other": "Other",
        "multisport": "Multisport",
    }
    normalized = str(raw).strip().lower()
    return mapping.get(normalized, normalized.capitalize())


def _display_step_intensity(step: SessionDisplaySimpleStep) -> str:
    target_type = _resolve_target_type(step)
    has_zone = any((step.target_hr_zone, step.target_pace_zone, step.target_power_zone, step.target_rpe_zone))
    if target_type and not has_zone and _step_has_explicit_range(step, target_type):
        range_label = _step_range_label(step, target_type, "", {})
        prefix = _custom_target_label(target_type, include_range=False)
        if prefix and range_label:
            return f"{prefix} {range_label}"
        return prefix or ""
    if (step.target_notes or "").strip():
        return (step.target_notes or "").strip()
    for zone in (step.target_pace_zone, step.target_hr_zone, step.target_power_zone, step.target_rpe_zone):
        if zone:
            return str(zone).strip()
    return ""


def _custom_target_label(target_type: str | None, *, include_range: bool) -> str:
    mapping = {
        "hr": "FC personalizada",
        "pace": "Ritmo personalizado",
        "power": "Potencia personalizada",
        "rpe": "RPE personalizado",
    }
    label = mapping.get(target_type or "", "")
    return label if include_range or label else ""


def _rpe_range_from_notes(notes: str | None) -> tuple[int, int] | None:
    if not notes:
        return None
    match = re.search(r"rpe\s*(\d+)\s*-\s*(\d+)", notes, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _session_type_to_default_step_type(session_type: str | None) -> str:
    mapping = {
        "easy": "steady",
        "base": "steady",
        "long": "steady",
        "tempo": "work",
        "hard": "work",
        "intervals": "work",
        "race": "work",
        "recovery": "recovery",
        "technique": "drills",
    }
    return mapping.get(session_type, "steady")


def _block_is_title_priority(block: SessionDisplayBlock) -> bool:
    if isinstance(block, SessionDisplayRepeatBlock):
        return True
    return block.step_type not in {"warmup", "cooldown", "recovery", "steady"}
