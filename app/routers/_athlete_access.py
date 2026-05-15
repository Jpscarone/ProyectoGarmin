from __future__ import annotations

from fastapi import HTTPException, status


def assert_same_athlete(*athlete_ids: int | None, detail: str = "Los recursos no pertenecen al mismo atleta.") -> int | None:
    resolved_ids = {athlete_id for athlete_id in athlete_ids if athlete_id is not None}
    if len(resolved_ids) > 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return next(iter(resolved_ids)) if resolved_ids else None


def get_athlete_id_from_session_group(group) -> int | None:
    training_day = getattr(group, "training_day", None)
    return getattr(training_day, "athlete_id", None)


def get_athlete_id_from_step(step) -> int | None:
    planned_session = getattr(step, "planned_session", None)
    return getattr(planned_session, "athlete_id", None)
