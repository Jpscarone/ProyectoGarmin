from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SessionDisplaySimpleStep:
    kind: Literal["simple"]
    step_order: int
    step_type: str
    repeat_count: int | None
    duration_sec: int | None
    distance_m: int | None
    target_hr_min: int | None
    target_hr_max: int | None
    target_power_min: int | None
    target_power_max: int | None
    target_pace_min_sec_km: int | None
    target_pace_max_sec_km: int | None
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


def build_session_display_blocks(planned_session_steps: list[object]) -> list[SessionDisplayBlock]:
    blocks: list[SessionDisplayBlock] = []
    current_repeat_steps: list[SessionDisplaySimpleStep] = []
    current_repeat_count: int | None = None

    for raw_step in planned_session_steps:
        display_step = SessionDisplaySimpleStep(
            kind="simple",
            step_order=raw_step.step_order,
            step_type=raw_step.step_type,
            repeat_count=raw_step.repeat_count,
            duration_sec=raw_step.duration_sec,
            distance_m=raw_step.distance_m,
            target_hr_min=raw_step.target_hr_min,
            target_hr_max=raw_step.target_hr_max,
            target_power_min=raw_step.target_power_min,
            target_power_max=raw_step.target_power_max,
            target_pace_min_sec_km=raw_step.target_pace_min_sec_km,
            target_pace_max_sec_km=raw_step.target_pace_max_sec_km,
            target_cadence_min=raw_step.target_cadence_min,
            target_cadence_max=raw_step.target_cadence_max,
            target_notes=raw_step.target_notes,
            source_step_id=raw_step.id,
        )

        if raw_step.repeat_count and raw_step.repeat_count > 1:
            if current_repeat_count == raw_step.repeat_count:
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
        return build_session_display_blocks(session_steps)

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
            target_hr_min=None,
            target_hr_max=None,
            target_power_min=None,
            target_power_max=None,
            target_pace_min_sec_km=None,
            target_pace_max_sec_km=None,
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

    repeat_blocks = [block for block in blocks if isinstance(block, SessionDisplayRepeatBlock)]
    if repeat_blocks:
        repeat_block = repeat_blocks[0]
        repeat_fragment = _display_repeat_fragment_short(repeat_block)
        intensity = _display_repeat_intensity(repeat_block)
        return " ".join(part for part in (sport_label, repeat_fragment, intensity) if part).strip()

    if blocks:
        simple_block = blocks[0]
        if isinstance(simple_block, SessionDisplaySimpleStep):
            fragment = _display_step_measurement(simple_block)
            intensity = simple_block.target_notes or ""
            return " ".join(part for part in (sport_label, fragment, intensity) if part).strip()

    return getattr(planned_session, "name", None)


def _display_step_measurement(step: SessionDisplaySimpleStep) -> str:
    if step.distance_m is not None:
        if step.distance_m >= 1000 and step.distance_m % 1000 == 0:
            return f"{int(step.distance_m / 1000)}km"
        if step.distance_m >= 1000:
            return f"{step.distance_m / 1000:.1f}km"
        return f"{step.distance_m}m"
    return format_duration_human_from_seconds(step.duration_sec)


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
    return (work_step.target_notes or "").strip()


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
    label = (step.target_notes or "").strip()
    if measurement and label:
        return f"{measurement} {label}"
    return measurement or label


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
