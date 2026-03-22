from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.session_template import SessionTemplate
from app.db.models.session_template_step import SessionTemplateStep
from app.db.models.training_day import TrainingDay
from app.schemas.planned_session import PlannedSessionCreate
from app.services.planned_session_service import create_planned_session, get_planned_session


@dataclass
class SessionTemplateStepInput:
    step_order: int
    step_type: str
    repeat_count: int | None = None
    duration_sec: int | None = None
    distance_m: int | None = None
    target_hr_min: int | None = None
    target_hr_max: int | None = None
    target_power_min: int | None = None
    target_power_max: int | None = None
    target_pace_min_sec_km: int | None = None
    target_pace_max_sec_km: int | None = None
    target_cadence_min: int | None = None
    target_cadence_max: int | None = None
    target_notes: str | None = None


@dataclass
class SessionTemplateInput:
    title: str
    sport_type: str | None = None
    discipline_variant: str | None = None
    session_type: str | None = None
    description_text: str | None = None
    expected_duration_min: int | None = None
    expected_distance_km: float | None = None
    expected_elevation_gain_m: float | None = None
    target_hr_zone: str | None = None
    target_power_zone: str | None = None
    target_notes: str | None = None
    is_active: bool = True
    steps: list[SessionTemplateStepInput] = field(default_factory=list)


def _session_template_base_statement() -> Select[tuple[SessionTemplate]]:
    return select(SessionTemplate).options(selectinload(SessionTemplate.steps))


def list_session_templates(
    db: Session,
    *,
    sport_type: str | None = None,
    session_type: str | None = None,
    include_inactive: bool = False,
) -> list[SessionTemplate]:
    statement = _session_template_base_statement().order_by(
        SessionTemplate.title.asc(),
        SessionTemplate.id.desc(),
    )
    if sport_type:
        statement = statement.where(SessionTemplate.sport_type == sport_type)
    if session_type:
        statement = statement.where(SessionTemplate.session_type == session_type)
    if not include_inactive:
        statement = statement.where(SessionTemplate.is_active.is_(True))
    return list(db.scalars(statement).all())


def get_session_template(db: Session, session_template_id: int) -> SessionTemplate | None:
    statement = _session_template_base_statement().where(SessionTemplate.id == session_template_id)
    return db.scalar(statement)


def create_session_template(db: Session, template_in: SessionTemplateInput) -> SessionTemplate:
    title = (template_in.title or "").strip()
    if not title:
        raise ValueError("La plantilla necesita un titulo.")

    template = SessionTemplate(
        title=title,
        sport_type=template_in.sport_type,
        discipline_variant=template_in.discipline_variant,
        session_type=template_in.session_type,
        description_text=template_in.description_text,
        expected_duration_min=template_in.expected_duration_min,
        expected_distance_km=template_in.expected_distance_km,
        expected_elevation_gain_m=template_in.expected_elevation_gain_m,
        target_hr_zone=template_in.target_hr_zone,
        target_power_zone=template_in.target_power_zone,
        target_notes=template_in.target_notes,
        is_active=template_in.is_active,
    )
    template.steps = [_build_template_step(step_in) for step_in in template_in.steps]
    db.add(template)
    db.commit()
    db.refresh(template)
    return get_session_template(db, template.id) or template


def update_session_template(db: Session, template: SessionTemplate, template_in: SessionTemplateInput) -> SessionTemplate:
    title = (template_in.title or "").strip()
    if not title:
        raise ValueError("La plantilla necesita un titulo.")

    template.title = title
    template.sport_type = template_in.sport_type
    template.discipline_variant = template_in.discipline_variant
    template.session_type = template_in.session_type
    template.description_text = template_in.description_text
    template.expected_duration_min = template_in.expected_duration_min
    template.expected_distance_km = template_in.expected_distance_km
    template.expected_elevation_gain_m = template_in.expected_elevation_gain_m
    template.target_hr_zone = template_in.target_hr_zone
    template.target_power_zone = template_in.target_power_zone
    template.target_notes = template_in.target_notes
    template.is_active = template_in.is_active
    template.steps.clear()
    template.steps.extend(_build_template_step(step_in) for step_in in template_in.steps)
    db.add(template)
    db.commit()
    db.refresh(template)
    return get_session_template(db, template.id) or template


def delete_session_template(db: Session, template: SessionTemplate) -> None:
    db.delete(template)
    db.commit()


def create_template_from_planned_session(
    db: Session,
    *,
    planned_session_id: int,
    title: str | None = None,
) -> SessionTemplate:
    planned_session = get_planned_session(db, planned_session_id)
    if planned_session is None:
        raise ValueError("La sesion no existe.")

    template_title = (title or planned_session.name or "").strip()
    if not template_title:
        raise ValueError("La plantilla necesita un titulo.")

    template_input = SessionTemplateInput(
        title=template_title,
        sport_type=planned_session.sport_type,
        discipline_variant=planned_session.discipline_variant,
        session_type=planned_session.session_type,
        description_text=planned_session.description_text,
        expected_duration_min=planned_session.expected_duration_min,
        expected_distance_km=planned_session.expected_distance_km,
        expected_elevation_gain_m=planned_session.expected_elevation_gain_m,
        target_hr_zone=planned_session.target_hr_zone,
        target_power_zone=planned_session.target_power_zone,
        target_notes=planned_session.target_notes,
        is_active=True,
        steps=[
            SessionTemplateStepInput(
                step_order=step.step_order,
                step_type=step.step_type,
                repeat_count=step.repeat_count,
                duration_sec=step.duration_sec,
                distance_m=step.distance_m,
                target_hr_min=step.target_hr_min,
                target_hr_max=step.target_hr_max,
                target_power_min=step.target_power_min,
                target_power_max=step.target_power_max,
                target_pace_min_sec_km=step.target_pace_min_sec_km,
                target_pace_max_sec_km=step.target_pace_max_sec_km,
                target_cadence_min=step.target_cadence_min,
                target_cadence_max=step.target_cadence_max,
                target_notes=step.target_notes,
            )
            for step in planned_session.planned_session_steps
        ],
    )
    return create_session_template(db, template_input)


def instantiate_template_for_day(
    db: Session,
    *,
    session_template_id: int,
    training_day_id: int,
) -> PlannedSession:
    template = get_session_template(db, session_template_id)
    if template is None:
        raise ValueError("La plantilla no existe.")

    training_day = db.get(TrainingDay, training_day_id)
    if training_day is None:
        raise ValueError("El dia no existe.")

    next_order = max((session.session_order for session in training_day.planned_sessions), default=0) + 1
    planned_session = create_planned_session(
        db,
        PlannedSessionCreate(
            training_day_id=training_day.id,
            athlete_id=training_day.athlete_id,
            session_group_id=None,
            sport_type=template.sport_type,
            discipline_variant=template.discipline_variant,
            name=template.title,
            description_text=template.description_text,
            session_type=template.session_type,
            session_order=next_order,
            planned_start_time=None,
            expected_duration_min=template.expected_duration_min,
            expected_distance_km=template.expected_distance_km,
            expected_elevation_gain_m=template.expected_elevation_gain_m,
            target_hr_zone=template.target_hr_zone,
            target_power_zone=template.target_power_zone,
            target_notes=template.target_notes,
            is_key_session=False,
        ),
    )

    for step in template.steps:
        db.add(
            PlannedSessionStep(
                planned_session_id=planned_session.id,
                step_order=step.step_order,
                step_type=step.step_type,
                repeat_count=step.repeat_count,
                duration_sec=step.duration_sec,
                distance_m=step.distance_m,
                target_hr_min=step.target_hr_min,
                target_hr_max=step.target_hr_max,
                target_power_min=step.target_power_min,
                target_power_max=step.target_power_max,
                target_pace_min_sec_km=step.target_pace_min_sec_km,
                target_pace_max_sec_km=step.target_pace_max_sec_km,
                target_cadence_min=step.target_cadence_min,
                target_cadence_max=step.target_cadence_max,
                target_notes=step.target_notes,
            )
        )

    db.commit()
    return get_planned_session(db, planned_session.id) or planned_session


def build_template_input_from_session(planned_session: PlannedSession) -> SessionTemplateInput:
    return SessionTemplateInput(
        title=planned_session.name,
        sport_type=planned_session.sport_type,
        discipline_variant=planned_session.discipline_variant,
        session_type=planned_session.session_type,
        description_text=planned_session.description_text,
        expected_duration_min=planned_session.expected_duration_min,
        expected_distance_km=planned_session.expected_distance_km,
        expected_elevation_gain_m=planned_session.expected_elevation_gain_m,
        target_hr_zone=planned_session.target_hr_zone,
        target_power_zone=planned_session.target_power_zone,
        target_notes=planned_session.target_notes,
        is_active=True,
        steps=[
            SessionTemplateStepInput(
                step_order=step.step_order,
                step_type=step.step_type,
                repeat_count=step.repeat_count,
                duration_sec=step.duration_sec,
                distance_m=step.distance_m,
                target_hr_min=step.target_hr_min,
                target_hr_max=step.target_hr_max,
                target_power_min=step.target_power_min,
                target_power_max=step.target_power_max,
                target_pace_min_sec_km=step.target_pace_min_sec_km,
                target_pace_max_sec_km=step.target_pace_max_sec_km,
                target_cadence_min=step.target_cadence_min,
                target_cadence_max=step.target_cadence_max,
                target_notes=step.target_notes,
            )
            for step in planned_session.planned_session_steps
        ],
    )


def _build_template_step(step_in: SessionTemplateStepInput) -> SessionTemplateStep:
    return SessionTemplateStep(
        step_order=step_in.step_order,
        step_type=step_in.step_type,
        repeat_count=step_in.repeat_count,
        duration_sec=step_in.duration_sec,
        distance_m=step_in.distance_m,
        target_hr_min=step_in.target_hr_min,
        target_hr_max=step_in.target_hr_max,
        target_power_min=step_in.target_power_min,
        target_power_max=step_in.target_power_max,
        target_pace_min_sec_km=step_in.target_pace_min_sec_km,
        target_pace_max_sec_km=step_in.target_pace_max_sec_km,
        target_cadence_min=step_in.target_cadence_min,
        target_cadence_max=step_in.target_cadence_max,
        target_notes=step_in.target_notes,
    )
