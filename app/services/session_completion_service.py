from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


STRENGTH_SPORT_ALIASES = {
    "strength",
    "strength_training",
    "functional_strength_training",
    "gym",
}


def is_strength_sport(value: str | None) -> bool:
    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in STRENGTH_SPORT_ALIASES


def has_linked_activity(planned_session: Any) -> bool:
    match = getattr(planned_session, "activity_match", None)
    return bool(match is not None and getattr(match, "garmin_activity", None) is not None)


def is_manually_completed_strength_session(planned_session: Any) -> bool:
    if not is_strength_sport(getattr(planned_session, "sport_type", None)):
        return False
    if getattr(planned_session, "completed_at", None) is None:
        return False
    source = (getattr(planned_session, "completion_source", None) or "").strip().lower()
    return source in {"manual", ""}


def is_session_completed(planned_session: Any) -> bool:
    return has_linked_activity(planned_session) or getattr(planned_session, "completed_at", None) is not None


def completion_method(planned_session: Any) -> str | None:
    if has_linked_activity(planned_session):
        return "garmin"
    if is_manually_completed_strength_session(planned_session):
        return "manual"
    return None


def completed_duration_sec(planned_session: Any) -> int | None:
    match = getattr(planned_session, "activity_match", None)
    activity = getattr(match, "garmin_activity", None) if match is not None else None
    if activity is not None and getattr(activity, "duration_sec", None) is not None:
        return int(activity.duration_sec)

    manual_value = getattr(planned_session, "manual_duration_sec", None)
    if manual_value is not None:
        return int(manual_value)

    expected_duration_min = getattr(planned_session, "expected_duration_min", None)
    if expected_duration_min is not None and is_manually_completed_strength_session(planned_session):
        return int(expected_duration_min) * 60
    return None


def completed_strength_rpe(planned_session: Any) -> int | None:
    manual_rpe = getattr(planned_session, "manual_strength_rpe", None)
    if manual_rpe is not None:
        return int(manual_rpe)
    planned_rpe = getattr(planned_session, "strength_rpe", None)
    return int(planned_rpe) if planned_rpe is not None else None


def completed_strength_focus(planned_session: Any) -> str | None:
    manual_focus = (getattr(planned_session, "manual_strength_focus", None) or "").strip()
    if manual_focus:
        return manual_focus
    planned_focus = (getattr(planned_session, "strength_focus", None) or "").strip()
    return planned_focus or None


def mark_strength_session_completed(
    planned_session: Any,
    *,
    duration_sec: int | None,
    strength_rpe: int | None,
    strength_focus: str | None,
    notes: str | None,
) -> None:
    if not is_strength_sport(getattr(planned_session, "sport_type", None)):
        raise ValueError("Solo las sesiones strength/gimnasio se pueden completar manualmente.")
    if has_linked_activity(planned_session):
        raise ValueError("La sesion ya tiene una actividad vinculada y no necesita completado manual.")

    planned_session.completed_at = datetime.now(timezone.utc)
    planned_session.completion_source = "manual"
    planned_session.manual_duration_sec = duration_sec
    planned_session.manual_strength_rpe = strength_rpe
    planned_session.manual_strength_focus = strength_focus
    planned_session.manual_completion_notes = notes


def clear_strength_session_completion(planned_session: Any) -> None:
    planned_session.completed_at = None
    planned_session.completion_source = None
    planned_session.manual_duration_sec = None
    planned_session.manual_strength_rpe = None
    planned_session.manual_strength_focus = None
    planned_session.manual_completion_notes = None
