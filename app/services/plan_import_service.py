from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.intensity_target_service import normalize_session_target_fields, normalize_step_target_fields
from app.services.plan_import_parser import PlanImportBlock, PlanImportPayload, PlanImportSession
from app.services.training_plan_service import select_default_training_plan


PreviewOperation = Literal["will_create", "will_update", "will_cancel", "conflict", "not_found", "invalid"]


@dataclass(slots=True)
class PlanImportPreviewItem:
    index: int
    action: str
    operation: PreviewOperation
    session_id: int | None = None
    date: str | None = None
    sport: str | None = None
    messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlanImportPreview:
    valid: bool
    operations: list[PlanImportPreviewItem]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "operations": [
                {
                    "index": item.index,
                    "action": item.action,
                    "operation": item.operation,
                    "session_id": item.session_id,
                    "date": item.date,
                    "sport": item.sport,
                    "messages": item.messages,
                }
                for item in self.operations
            ],
            "errors": self.errors,
        }


def preview_plan_import(db: Session, athlete_id: int, payload: PlanImportPayload) -> dict[str, Any]:
    preview = _build_preview(db, athlete_id, payload)
    return preview.to_dict()


def commit_plan_import(db: Session, athlete_id: int, payload: PlanImportPayload) -> dict[str, Any]:
    preview = _build_preview(db, athlete_id, payload)
    if not preview.valid:
        return _commit_result(errors=preview.errors, skipped=len(payload.sessions))

    result = _commit_result()
    try:
        for session_in, preview_item in zip(payload.sessions, preview.operations, strict=True):
            if preview_item.operation == "will_create":
                created = _create_session(db, athlete_id, session_in)
                result["created"] += 1
                result["affected_session_ids"].append(created.id)
            elif preview_item.operation == "will_update":
                target = _resolve_target_for_commit(db, athlete_id, session_in)
                if target is None:
                    raise RuntimeError("No se encontro la sesion a actualizar durante commit.")
                _update_session(db, target, session_in, replace_blocks=bool(session_in.blocks))
                result["updated"] += 1
                result["affected_session_ids"].append(target.id)
            elif preview_item.operation == "will_cancel":
                target = _resolve_target_for_commit(db, athlete_id, session_in)
                if target is None:
                    raise RuntimeError("No se encontro la sesion a cancelar durante commit.")
                _cancel_session(target, session_in.reason)
                db.add(target)
                result["cancelled"] += 1
                result["affected_session_ids"].append(target.id)
            else:
                result["skipped"] += 1
        db.commit()
    except Exception as exc:
        db.rollback()
        return _commit_result(errors=[str(exc)], skipped=len(payload.sessions))
    return result


def _build_preview(db: Session, athlete_id: int, payload: PlanImportPayload) -> PlanImportPreview:
    operations: list[PlanImportPreviewItem] = []
    errors: list[str] = []
    seen_create_keys: set[tuple[date, str]] = set()

    for index, session_in in enumerate(payload.sessions, start=1):
        item = _preview_session(db, athlete_id, payload, session_in, index)
        key = (session_in.date, session_in.sport) if session_in.date and session_in.sport else None
        if session_in.action in {"create", "upsert"} and key is not None:
            if key in seen_create_keys:
                item.operation = "conflict"
                item.messages.append("Hay mas de una operacion del bloque para la misma fecha y sport.")
            seen_create_keys.add(key)
        if item.operation in {"conflict", "not_found", "invalid"}:
            errors.extend(item.messages)
        operations.append(item)
    return PlanImportPreview(valid=not errors, operations=operations, errors=errors)


def _preview_session(
    db: Session,
    athlete_id: int,
    payload: PlanImportPayload,
    session_in: PlanImportSession,
    index: int,
) -> PlanImportPreviewItem:
    item = PlanImportPreviewItem(
        index=index,
        action=session_in.action,
        operation="invalid",
        session_id=session_in.session_id,
        date=session_in.date.isoformat() if session_in.date else None,
        sport=session_in.sport,
    )
    messages = _validate_session_payload(payload, session_in)
    if messages:
        item.messages = messages
        return item

    if session_in.action == "create":
        matches = _find_sessions_by_date_sport(db, athlete_id, session_in.date, session_in.sport)
        if matches:
            item.operation = "conflict"
            item.messages = ["Ya existe una sesion para la misma fecha y sport."]
        else:
            item.operation = "will_create"
        return item

    if session_in.action == "upsert":
        matches = _find_sessions_by_date_sport(db, athlete_id, session_in.date, session_in.sport)
        if len(matches) > 1:
            item.operation = "conflict"
            item.messages = ["Hay multiples sesiones para la misma fecha y sport."]
        elif len(matches) == 1:
            item.operation = "will_update"
            item.session_id = matches[0].id
        else:
            item.operation = "will_create"
        return item

    target_result = _resolve_target_for_preview(db, athlete_id, session_in)
    if target_result["status"] != "ok":
        item.operation = target_result["status"]
        item.messages = target_result["messages"]
        return item

    target = target_result["session"]
    item.session_id = target.id
    item.operation = "will_cancel" if session_in.action == "cancel" else "will_update"
    return item


def _validate_session_payload(payload: PlanImportPayload, session_in: PlanImportSession) -> list[str]:
    errors: list[str] = []
    if payload.start_date and session_in.date and session_in.date < payload.start_date:
        errors.append("La fecha esta fuera de START_DATE/END_DATE.")
    if payload.end_date and session_in.date and session_in.date > payload.end_date:
        errors.append("La fecha esta fuera de START_DATE/END_DATE.")
    if session_in.action != "cancel":
        for position, block in enumerate(session_in.blocks, start=1):
            block_errors = _validate_block(block)
            errors.extend([f"Bloque {position}: {message}" for message in block_errors])
    return errors


def _validate_block(block: PlanImportBlock) -> list[str]:
    errors: list[str] = []
    if block.value is None:
        errors.append("VALUE es obligatorio.")
    elif block.value <= 0:
        errors.append("VALUE debe ser mayor a cero.")
    if not block.unit:
        errors.append("UNIT es obligatorio.")
    elif block.unit.strip().lower() not in {"min", "minute", "minutes", "sec", "second", "seconds", "km", "m"}:
        errors.append("UNIT no soportado.")
    for lower, upper, label in (
        (block.rpe_min, block.rpe_max, "RPE"),
        (block.hr_min, block.hr_max, "HR"),
        (block.pace_min, block.pace_max, "PACE"),
    ):
        if lower is not None and upper is not None and lower > upper:
            errors.append(f"{label}_MIN no puede ser mayor que {label}_MAX.")
    return errors


def _resolve_target_for_preview(db: Session, athlete_id: int, session_in: PlanImportSession) -> dict[str, Any]:
    target = _resolve_target_for_commit(db, athlete_id, session_in)
    if target is not None:
        return {"status": "ok", "session": target, "messages": []}
    if session_in.session_id is not None:
        return {"status": "not_found", "session": None, "messages": ["SESSION_ID inexistente para este atleta."]}
    matches = _find_sessions_by_date_sport(db, athlete_id, session_in.date, session_in.sport)
    if len(matches) > 1:
        return {"status": "conflict", "session": None, "messages": ["Hay multiples coincidencias para DATE + SPORT."]}
    return {"status": "not_found", "session": None, "messages": ["No se encontro sesion para DATE + SPORT."]}


def _resolve_target_for_commit(db: Session, athlete_id: int, session_in: PlanImportSession) -> PlannedSession | None:
    if session_in.session_id is not None:
        return db.scalar(
            select(PlannedSession)
            .where(PlannedSession.id == session_in.session_id, PlannedSession.athlete_id == athlete_id)
            .options(selectinload(PlannedSession.training_day), selectinload(PlannedSession.planned_session_steps))
        )
    matches = _find_sessions_by_date_sport(db, athlete_id, session_in.date, session_in.sport)
    return matches[0] if len(matches) == 1 else None


def _find_sessions_by_date_sport(
    db: Session,
    athlete_id: int,
    target_date: date | None,
    sport: str | None,
) -> list[PlannedSession]:
    if target_date is None or not sport:
        return []
    return list(
        db.scalars(
            select(PlannedSession)
            .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
            .where(
                PlannedSession.athlete_id == athlete_id,
                TrainingDay.day_date == target_date,
                PlannedSession.sport_type == sport,
            )
            .options(selectinload(PlannedSession.training_day), selectinload(PlannedSession.planned_session_steps))
            .order_by(PlannedSession.id.asc())
        ).all()
    )


def _create_session(db: Session, athlete_id: int, session_in: PlanImportSession) -> PlannedSession:
    training_day = _get_or_create_training_day(db, athlete_id, session_in.date, session_in.sport)
    session_order = _next_session_order(db, training_day.id)
    session = PlannedSession(
        athlete_id=athlete_id,
        training_day_id=training_day.id,
        sport_type=session_in.sport,
        modality=session_in.modality,
        name=session_in.name or "Sesion importada",
        description_text=session_in.notes,
        session_order=session_order,
        target_notes=session_in.notes,
    )
    _apply_session_blocks(session, session_in.blocks)
    db.add(session)
    db.flush()
    _replace_blocks(db, session, session_in.blocks)
    db.flush()
    return session


def _update_session(db: Session, session: PlannedSession, session_in: PlanImportSession, *, replace_blocks: bool) -> None:
    if session_in.date is not None and (session.training_day is None or session.training_day.day_date != session_in.date):
        session.training_day_id = _get_or_create_training_day(db, session.athlete_id, session_in.date, session_in.sport or session.sport_type).id
    if session_in.sport is not None:
        session.sport_type = session_in.sport
    if session_in.modality is not None:
        session.modality = session_in.modality
    if session_in.name is not None:
        session.name = session_in.name
    if session_in.notes is not None:
        session.description_text = session_in.notes
        session.target_notes = session_in.notes
    if session_in.blocks:
        _apply_session_blocks(session, session_in.blocks)
    data = normalize_session_target_fields(
        {
            "target_type": session.target_type,
            "target_hr_zone": session.target_hr_zone,
            "target_pace_zone": session.target_pace_zone,
            "target_power_zone": session.target_power_zone,
            "target_rpe_zone": session.target_rpe_zone,
        }
    )
    for key, value in data.items():
        setattr(session, key, value)
    db.add(session)
    db.flush()
    if replace_blocks:
        _replace_blocks(db, session, session_in.blocks)


def _cancel_session(session: PlannedSession, reason: str | None) -> None:
    session.completion_source = "cancelled"
    if reason:
        cancellation_note = f"Cancelada: {reason}"
        if session.manual_completion_notes:
            session.manual_completion_notes = f"{session.manual_completion_notes}\n{cancellation_note}"
        else:
            session.manual_completion_notes = cancellation_note
        if session.target_notes:
            session.target_notes = f"{session.target_notes}\n{cancellation_note}"
        else:
            session.target_notes = cancellation_note


def _get_or_create_training_day(
    db: Session,
    athlete_id: int,
    target_date: date | None,
    sport: str | None,
) -> TrainingDay:
    if target_date is None:
        raise ValueError("DATE es obligatorio para crear o mover sesiones.")
    existing = db.scalar(
        select(TrainingDay)
        .where(TrainingDay.athlete_id == athlete_id, TrainingDay.day_date == target_date)
        .order_by(TrainingDay.id.asc())
    )
    if existing is not None:
        return existing
    plan = _resolve_plan_for_date(db, athlete_id, target_date)
    if plan is None:
        raise ValueError("El atleta no tiene un plan disponible para crear training_day.")
    training_day = TrainingDay(
        athlete_id=athlete_id,
        training_plan_id=plan.id,
        day_date=target_date,
        day_type=sport,
    )
    db.add(training_day)
    db.flush()
    return training_day


def _resolve_plan_for_date(db: Session, athlete_id: int, target_date: date) -> TrainingPlan | None:
    plan = select_default_training_plan(db, athlete_id=athlete_id, today=target_date)
    if plan is not None:
        return plan
    return db.scalar(
        select(TrainingPlan)
        .where(TrainingPlan.athlete_id == athlete_id)
        .order_by(TrainingPlan.start_date.desc().nullslast(), TrainingPlan.id.desc())
    )


def _next_session_order(db: Session, training_day_id: int) -> int:
    sessions = list(
        db.scalars(
            select(PlannedSession)
            .where(PlannedSession.training_day_id == training_day_id)
            .order_by(PlannedSession.session_order.desc())
            .limit(1)
        ).all()
    )
    return (sessions[0].session_order + 1) if sessions else 1


def _apply_session_blocks(session: PlannedSession, blocks: list[PlanImportBlock]) -> None:
    duration_min = 0
    distance_km = 0.0
    for block in blocks:
        unit = (block.unit or "").strip().lower()
        if unit in {"min", "minute", "minutes"} and block.value is not None:
            duration_min += int(round(block.value))
        elif unit in {"sec", "second", "seconds"} and block.value is not None:
            duration_min += int(round(block.value / 60))
        elif unit == "km" and block.value is not None:
            distance_km += float(block.value)
        elif unit == "m" and block.value is not None:
            distance_km += float(block.value) / 1000
    if duration_min:
        session.expected_duration_min = duration_min
    if distance_km:
        session.expected_distance_km = round(distance_km, 3)
    first_target = next((block for block in blocks if block.intensity or block.zone or block.rpe_min or block.hr_min or block.pace_min), None)
    if first_target is not None:
        _apply_target(session, first_target)


def _apply_target(session: PlannedSession, block: PlanImportBlock) -> None:
    intensity = (block.intensity or "").strip().lower()
    zone = block.zone
    if intensity == "hr" or block.hr_min is not None or block.hr_max is not None:
        session.target_type = "hr"
        session.target_hr_zone = zone
    elif intensity == "pace" or block.pace_min is not None or block.pace_max is not None:
        session.target_type = "pace"
        session.target_pace_zone = zone
    elif intensity == "rpe" or block.rpe_min is not None or block.rpe_max is not None:
        session.target_type = "rpe"
        session.target_rpe_zone = zone or _range_label("RPE", block.rpe_min, block.rpe_max)
    else:
        session.target_type = None


def _replace_blocks(db: Session, session: PlannedSession, blocks: list[PlanImportBlock]) -> None:
    db.execute(delete(PlannedSessionStep).where(PlannedSessionStep.planned_session_id == session.id))
    for order, block in enumerate(blocks, start=1):
        data = _step_data(session.id, order, block)
        data = normalize_step_target_fields(data, session.athlete)
        db.add(PlannedSessionStep(**data))
    db.flush()


def _step_data(session_id: int, order: int, block: PlanImportBlock) -> dict[str, Any]:
    unit = (block.unit or "").strip().lower()
    value = block.value or 0
    data: dict[str, Any] = {
        "planned_session_id": session_id,
        "step_order": order,
        "step_type": "steady",
        "target_type": block.intensity,
        "target_hr_zone": block.zone if block.intensity == "hr" else None,
        "target_hr_min": block.hr_min,
        "target_hr_max": block.hr_max,
        "target_pace_zone": block.zone if block.intensity == "pace" else None,
        "target_pace_min_sec_km": block.pace_min,
        "target_pace_max_sec_km": block.pace_max,
        "target_rpe_zone": block.zone or _range_label("RPE", block.rpe_min, block.rpe_max) if block.intensity == "rpe" else None,
        "target_notes": block.notes,
    }
    if unit in {"min", "minute", "minutes"}:
        data["duration_sec"] = int(round(value * 60))
    elif unit in {"sec", "second", "seconds"}:
        data["duration_sec"] = int(round(value))
    elif unit == "km":
        data["distance_m"] = int(round(value * 1000))
    elif unit == "m":
        data["distance_m"] = int(round(value))
    return data


def _range_label(prefix: str, lower: int | None, upper: int | None) -> str | None:
    if lower is None and upper is None:
        return None
    if lower is not None and upper is not None:
        return f"{prefix} {lower}-{upper}"
    return f"{prefix} {lower or upper}"


def _commit_result(*, errors: list[str] | None = None, skipped: int = 0) -> dict[str, Any]:
    return {
        "created": 0,
        "updated": 0,
        "cancelled": 0,
        "skipped": skipped,
        "errors": errors or [],
        "affected_session_ids": [],
    }
