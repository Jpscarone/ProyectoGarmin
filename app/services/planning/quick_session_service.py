from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from sqlalchemy.orm import Session

from app.db.models.training_day import TrainingDay
from app.db.models.planned_session import PlannedSession
from app.schemas.planned_session import PlannedSessionCreate
from app.schemas.planned_session_step import PlannedSessionStepCreate
from app.services.planned_session_service import create_planned_session
from app.services.planned_session_step_service import create_step
from app.services.planning.parser import parse_session_text


@dataclass
class QuickSessionResult:
    planned_session: PlannedSession
    created_steps: int
    parse_mode: str


@dataclass
class SessionAdvancedData:
    name: str | None = None
    session_order: int | None = None
    planned_start_time: time | None = None
    sport_type: str | None = None
    discipline_variant: str | None = None
    session_type: str | None = None
    session_group_id: int | None = None
    is_key_session: bool | None = None
    expected_duration_min: int | None = None
    expected_distance_km: float | None = None
    expected_elevation_gain_m: float | None = None
    target_hr_zone: str | None = None
    target_power_zone: str | None = None
    target_notes: str | None = None
    description_text: str | None = None


def create_session_from_quick_mode(
    db: Session,
    *,
    training_day_id: int,
    mode: str,
    sport_type: str | None = None,
    discipline_variant: str | None = None,
    name: str | None = None,
    description_text: str | None = None,
    expected_duration_min: int | None = None,
    expected_distance_km: float | None = None,
    target_hr_zone: str | None = None,
    target_power_zone: str | None = None,
    target_notes: str | None = None,
    raw_text: str | None = None,
    is_key_session: bool = False,
    advanced_data: SessionAdvancedData | None = None,
) -> QuickSessionResult:
    advanced = advanced_data or SessionAdvancedData()
    normalized_mode = mode.strip().lower()
    if normalized_mode == "simple":
        return create_quick_session(
            db,
            training_day_id=training_day_id,
            sport_type=sport_type,
            discipline_variant=discipline_variant,
            name=(name or "").strip(),
            description_text=description_text,
            expected_duration_min=expected_duration_min,
            expected_distance_km=expected_distance_km,
            target_hr_zone=target_hr_zone,
            target_power_zone=target_power_zone,
            target_notes=target_notes,
            is_key_session=is_key_session,
            advanced_data=advanced,
        )

    if normalized_mode in {"text", "builder"}:
        if not raw_text or not raw_text.strip():
            raise ValueError("Escribi una sesion o arma al menos un bloque antes de crearla.")
        return create_session_from_natural_language(
            db,
            training_day_id=training_day_id,
            raw_text=raw_text,
            sport_type_override=sport_type,
            discipline_variant_override=discipline_variant,
            is_key_session=is_key_session,
            advanced_data=advanced,
            parse_mode=normalized_mode,
        )

    raise ValueError("Modo de creacion no valido.")


def create_quick_session(
    db: Session,
    *,
    training_day_id: int,
    sport_type: str | None,
    discipline_variant: str | None,
    name: str,
    description_text: str | None,
    expected_duration_min: int | None,
    expected_distance_km: float | None,
    target_hr_zone: str | None,
    target_power_zone: str | None,
    target_notes: str | None,
    is_key_session: bool,
    advanced_data: SessionAdvancedData | None = None,
) -> QuickSessionResult:
    advanced = advanced_data or SessionAdvancedData()
    parse_source = " ".join(part.strip() for part in (name, description_text or "") if part and part.strip())
    try:
        parsed = parse_session_text(parse_source, fallback_sport_type=sport_type) if parse_source else None
    except ValueError:
        parsed = None

    session_order = advanced.session_order or _next_session_order(db, training_day_id)
    planned_session = create_planned_session(db, _build_simple_session_create(
        training_day_id=training_day_id,
        session_order=session_order,
        sport_type=sport_type or (parsed.sport_type if parsed else None),
        discipline_variant=discipline_variant or (parsed.discipline_variant if parsed else None),
        name=name,
        description_text=description_text,
        session_type=parsed.session_type if parsed else None,
        expected_duration_min=expected_duration_min if expected_duration_min is not None else (parsed.expected_duration_min if parsed else None),
        expected_distance_km=expected_distance_km if expected_distance_km is not None else (parsed.expected_distance_km if parsed else None),
        target_hr_zone=target_hr_zone or (parsed.target_hr_zone if parsed else None),
        target_power_zone=target_power_zone or (parsed.target_power_zone if parsed else None),
        target_notes=target_notes or (parsed.target_notes if parsed else None),
        is_key_session=is_key_session,
        advanced=advanced,
    ))
    generated_step = _create_default_step_for_session(db, planned_session)
    db.refresh(planned_session)
    return QuickSessionResult(planned_session=planned_session, created_steps=1 if generated_step else 0, parse_mode="quick")


def create_session_from_natural_language(
    db: Session,
    *,
    training_day_id: int,
    raw_text: str,
    sport_type_override: str | None = None,
    discipline_variant_override: str | None = None,
    is_key_session: bool = False,
    advanced_data: SessionAdvancedData | None = None,
    parse_mode: str | None = None,
) -> QuickSessionResult:
    advanced = advanced_data or SessionAdvancedData()
    session_order = advanced.session_order or _next_session_order(db, training_day_id)
    parsed = parse_session_text(raw_text, fallback_sport_type=sport_type_override)

    planned_session = create_planned_session(db, _build_parsed_session_create(
        training_day_id=training_day_id,
        session_order=session_order,
        parsed=parsed,
        discipline_variant_override=discipline_variant_override,
        is_key_session=is_key_session,
        advanced=advanced,
    ))

    created_steps = 0
    if parsed.steps:
        for step in parsed.steps:
            create_step(
                db,
                PlannedSessionStepCreate(
                    planned_session_id=planned_session.id,
                    step_order=step.step_order,
                    step_type=step.step_type,
                    repeat_count=step.repeat_count,
                    duration_sec=step.duration_sec,
                    distance_m=step.distance_m,
                    target_notes=step.target_notes,
                ),
            )
            created_steps += 1

        db.refresh(planned_session)
    else:
        generated_step = _create_default_step_for_session(db, planned_session)
        created_steps = 1 if generated_step else 0

    return QuickSessionResult(
        planned_session=planned_session,
        created_steps=created_steps,
        parse_mode=parse_mode or parsed.parse_confidence,
    )


def _next_session_order(db: Session, training_day_id: int) -> int:
    training_day = db.get(TrainingDay, training_day_id)
    if training_day is None or not training_day.planned_sessions:
        return 1
    return max(session.session_order for session in training_day.planned_sessions) + 1


def _create_default_step_for_session(db: Session, planned_session: PlannedSession):
    duration_sec = planned_session.expected_duration_min * 60 if planned_session.expected_duration_min is not None else None
    distance_m = int(round(planned_session.expected_distance_km * 1000)) if planned_session.expected_distance_km is not None else None
    if duration_sec is None and distance_m is None:
        return None

    return create_step(
        db,
        PlannedSessionStepCreate(
            planned_session_id=planned_session.id,
            step_order=1,
            step_type=_default_step_type(planned_session.session_type),
            repeat_count=None,
            duration_sec=duration_sec,
            distance_m=distance_m,
            target_notes=planned_session.target_notes or _default_target_note(planned_session.session_type),
        ),
    )


def _build_simple_session_create(
    *,
    training_day_id: int,
    session_order: int,
    sport_type: str | None,
    discipline_variant: str | None,
    name: str,
    description_text: str | None,
    session_type: str | None,
    expected_duration_min: int | None,
    expected_distance_km: float | None,
    target_hr_zone: str | None,
    target_power_zone: str | None,
    target_notes: str | None,
    is_key_session: bool,
    advanced: SessionAdvancedData,
) -> PlannedSessionCreate:
    return PlannedSessionCreate(
        training_day_id=training_day_id,
        sport_type=sport_type or advanced.sport_type,
        discipline_variant=discipline_variant or advanced.discipline_variant,
        name=advanced.name or name,
        description_text=description_text or advanced.description_text,
        session_type=session_type or advanced.session_type,
        session_order=session_order,
        planned_start_time=advanced.planned_start_time,
        session_group_id=advanced.session_group_id,
        expected_duration_min=expected_duration_min if expected_duration_min is not None else advanced.expected_duration_min,
        expected_distance_km=expected_distance_km if expected_distance_km is not None else advanced.expected_distance_km,
        expected_elevation_gain_m=advanced.expected_elevation_gain_m,
        target_hr_zone=target_hr_zone or advanced.target_hr_zone,
        target_power_zone=target_power_zone or advanced.target_power_zone,
        target_notes=target_notes or advanced.target_notes,
        is_key_session=advanced.is_key_session if advanced.is_key_session is not None else is_key_session,
    )


def _build_parsed_session_create(
    *,
    training_day_id: int,
    session_order: int,
    parsed,
    discipline_variant_override: str | None,
    is_key_session: bool,
    advanced: SessionAdvancedData,
) -> PlannedSessionCreate:
    return PlannedSessionCreate(
        training_day_id=training_day_id,
        sport_type=parsed.sport_type or advanced.sport_type,
        discipline_variant=discipline_variant_override or parsed.discipline_variant or advanced.discipline_variant,
        name=advanced.name or parsed.name,
        description_text=parsed.description_text or advanced.description_text,
        session_type=parsed.session_type or advanced.session_type,
        session_order=session_order,
        planned_start_time=advanced.planned_start_time,
        session_group_id=advanced.session_group_id,
        expected_duration_min=parsed.expected_duration_min if parsed.expected_duration_min is not None else advanced.expected_duration_min,
        expected_distance_km=parsed.expected_distance_km if parsed.expected_distance_km is not None else advanced.expected_distance_km,
        expected_elevation_gain_m=advanced.expected_elevation_gain_m,
        target_hr_zone=parsed.target_hr_zone or advanced.target_hr_zone,
        target_power_zone=parsed.target_power_zone or advanced.target_power_zone,
        target_notes=parsed.target_notes or advanced.target_notes,
        is_key_session=advanced.is_key_session if advanced.is_key_session is not None else is_key_session,
    )


def _default_step_type(session_type: str | None) -> str:
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


def _default_target_note(session_type: str | None) -> str | None:
    mapping = {
        "easy": "suave",
        "base": "base",
        "long": "fondo",
        "tempo": "tempo",
        "hard": "fuerte",
        "recovery": "recuperacion",
        "technique": "tecnica",
    }
    return mapping.get(session_type)
