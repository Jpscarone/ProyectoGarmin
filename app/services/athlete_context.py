from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.models.athlete import Athlete
from app.db.models.training_plan import TrainingPlan
from app.services.athlete_service import ATHLETE_STATUS_ACTIVE, get_active_athletes, get_athlete
from app.services.training_plan_service import get_training_plan, select_default_training_plan


CURRENT_ATHLETE_SESSION_KEY = "current_athlete_id"
CURRENT_TRAINING_PLAN_SESSION_KEY = "current_training_plan_id"


@dataclass
class AthleteContext:
    athlete: Athlete | None
    active_athletes: list[Athlete]
    needs_selection: bool = False
    message: str | None = None


def get_current_athlete(
    request: Request,
    db: Session,
    *,
    athlete_id: int | None = None,
    require_selected: bool = False,
) -> Athlete | None:
    context = resolve_athlete_context(request, db, athlete_id=athlete_id)
    if context.athlete is not None:
        set_current_athlete(request, context.athlete.id)
        return context.athlete
    if require_selected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=context.message or "Selecciona un atleta activo para continuar.",
        )
    return None


def resolve_athlete_context(
    request: Request,
    db: Session,
    *,
    athlete_id: int | None = None,
) -> AthleteContext:
    active_athletes = get_active_athletes(db)
    selected_id = athlete_id or _query_int(request, "athlete_id") or _session_int(request, CURRENT_ATHLETE_SESSION_KEY)

    if selected_id is not None:
        athlete = get_athlete(db, selected_id)
        if athlete is not None and athlete.status == ATHLETE_STATUS_ACTIVE:
            return AthleteContext(athlete=athlete, active_athletes=active_athletes)
        clear_current_athlete(request)
        return AthleteContext(
            athlete=None,
            active_athletes=active_athletes,
            needs_selection=True,
            message="El atleta seleccionado no existe o no esta activo.",
        )

    if len(active_athletes) == 1:
        return AthleteContext(athlete=active_athletes[0], active_athletes=active_athletes)

    if len(active_athletes) > 1:
        return AthleteContext(
            athlete=None,
            active_athletes=active_athletes,
            needs_selection=True,
            message="Selecciona con que atleta queres trabajar.",
        )

    return AthleteContext(
        athlete=None,
        active_athletes=[],
        needs_selection=True,
        message="No hay atletas activos. Crea o reactiva un atleta para continuar.",
    )


def set_current_athlete(request: Request, athlete_id: int) -> None:
    request.session[CURRENT_ATHLETE_SESSION_KEY] = int(athlete_id)


def clear_current_athlete(request: Request) -> None:
    request.session.pop(CURRENT_ATHLETE_SESSION_KEY, None)
    request.session.pop(CURRENT_TRAINING_PLAN_SESSION_KEY, None)


def set_current_training_plan(request: Request, training_plan_id: int | None) -> None:
    if training_plan_id is None:
        request.session.pop(CURRENT_TRAINING_PLAN_SESSION_KEY, None)
        return
    request.session[CURRENT_TRAINING_PLAN_SESSION_KEY] = int(training_plan_id)


def get_current_training_plan(
    request: Request,
    db: Session,
    athlete: Athlete | None,
    *,
    training_plan_id: int | None = None,
    require_selected: bool = False,
) -> TrainingPlan | None:
    if athlete is None:
        if require_selected:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Selecciona un atleta activo.")
        return None

    requested_plan_id = training_plan_id or _query_int(request, "training_plan_id")
    if requested_plan_id is not None:
        plan = get_training_plan(db, requested_plan_id)
        if plan is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training plan not found")
        if plan.athlete_id != athlete.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El plan no pertenece al atleta seleccionado.")
        set_current_training_plan(request, plan.id)
        return plan

    session_plan_id = _session_int(request, CURRENT_TRAINING_PLAN_SESSION_KEY)
    if session_plan_id is not None:
        plan = get_training_plan(db, session_plan_id)
        if plan is not None and plan.athlete_id == athlete.id:
            return plan
        request.session.pop(CURRENT_TRAINING_PLAN_SESSION_KEY, None)

    plan = select_default_training_plan(db, athlete_id=athlete.id, today=date.today())
    if plan is not None:
        set_current_training_plan(request, plan.id)
        return plan
    if require_selected:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El atleta seleccionado no tiene un plan disponible.")
    return None


def build_global_context(request: Request, db: Session) -> dict[str, Any]:
    context = resolve_athlete_context(request, db)
    athlete = context.athlete
    plan = get_current_training_plan(request, db, athlete) if athlete is not None else None
    return {
        "current_athlete": athlete,
        "current_training_plan": plan,
        "active_athletes": context.active_athletes,
        "athlete_context_message": context.message,
        "needs_athlete_selection": context.needs_selection and athlete is None,
    }


def _query_int(request: Request, key: str) -> int | None:
    value = request.query_params.get(key)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _session_int(request: Request, key: str) -> int | None:
    value = request.session.get(key)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
