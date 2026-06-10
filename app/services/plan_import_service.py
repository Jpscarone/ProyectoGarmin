from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
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
    warnings: list[str]

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
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class PlanImportVerifyItem:
    index: int
    action: str
    expected: dict[str, Any]
    actual: dict[str, Any] | None = None
    reason: str | None = None
    fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "expected": self.expected,
            "actual": self.actual,
            "reason": self.reason,
            "fields": self.fields,
        }


def preview_plan_import(db: Session, athlete_id: int, payload: PlanImportPayload) -> dict[str, Any]:
    preview = _build_preview(db, athlete_id, payload)
    return preview.to_dict()


def verify_plan_import(db: Session, athlete_id: int, payload: PlanImportPayload) -> dict[str, Any]:
    warnings: list[str] = list(payload.warnings)
    expected_sessions = [item for item in payload.sessions]
    for session_in in expected_sessions:
        warnings.extend(_normalize_imported_session_type(session_in))

    week_start_date, week_end_date = _resolve_verify_window(payload)
    missing_sessions: list[dict[str, Any]] = []
    different_sessions: list[dict[str, Any]] = []
    matched_session_ids: set[int] = set()
    matched_sessions = 0

    for index, session_in in enumerate(expected_sessions, start=1):
        target, resolution_reason = _resolve_target_for_verify(db, athlete_id, session_in)
        expected_payload = _serialize_expected_import_session(session_in)
        if target is None:
            missing_sessions.append(
                PlanImportVerifyItem(
                    index=index,
                    action=session_in.action,
                    expected=expected_payload,
                    reason=resolution_reason or "No se encontro una sesion coincidente.",
                ).to_dict()
            )
            continue

        matched_session_ids.add(target.id)
        actual_payload = _serialize_actual_verify_session(target)
        field_differences = _compare_verify_session_fields(session_in, target)
        if field_differences:
            different_sessions.append(
                PlanImportVerifyItem(
                    index=index,
                    action=session_in.action,
                    expected=expected_payload,
                    actual=actual_payload,
                    reason="La sesion existe pero difiere de lo importado.",
                    fields=field_differences,
                ).to_dict()
            )
            continue
        matched_sessions += 1

    extra_sessions_same_week = [
        _serialize_actual_verify_session(item)
        for item in _find_extra_sessions_in_window(
            db,
            athlete_id=athlete_id,
            week_start_date=week_start_date,
            week_end_date=week_end_date,
            matched_session_ids=matched_session_ids,
        )
    ]
    if extra_sessions_same_week:
        warnings.append("Hay sesiones extra en la misma semana que no aparecen en el bloque importable.")

    valid = not missing_sessions and not different_sessions
    if valid and not extra_sessions_same_week:
        summary = "Importacion verificada sin diferencias."
    elif valid:
        summary = "Importacion verificada. Hay sesiones extra en la misma semana."
    else:
        summary = "La importacion verificada tiene sesiones faltantes o diferencias."

    return {
        "valid": valid,
        "week_start_date": week_start_date.isoformat(),
        "week_end_date": week_end_date.isoformat(),
        "expected_sessions": len(expected_sessions),
        "matched_sessions": matched_sessions,
        "missing_sessions": missing_sessions,
        "different_sessions": different_sessions,
        "extra_sessions_same_week": extra_sessions_same_week,
        "summary": summary,
        "warnings": _dedupe_preserve_order(warnings),
    }


def commit_plan_import(db: Session, athlete_id: int, payload: PlanImportPayload) -> dict[str, Any]:
    preview = _build_preview(db, athlete_id, payload)
    if not preview.valid:
        result = _commit_result(errors=preview.errors, skipped=len(payload.sessions))
        result["warnings"] = list(preview.warnings)
        return result

    result = _commit_result()
    result["warnings"] = list(preview.warnings)
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
    warnings: list[str] = list(payload.warnings)
    seen_create_keys: set[tuple[date, str]] = set()

    for index, session_in in enumerate(payload.sessions, start=1):
        session_warnings = _normalize_imported_session_type(session_in)
        warnings.extend(session_warnings)
        item = _preview_session(db, athlete_id, payload, session_in, index)
        item.messages.extend(session_warnings)
        key = (session_in.date, session_in.sport) if session_in.date and session_in.sport else None
        if session_in.action in {"create", "upsert"} and key is not None:
            if key in seen_create_keys:
                item.operation = "conflict"
                item.messages.append("Hay mas de una operacion del bloque para la misma fecha y sport.")
            seen_create_keys.add(key)
        if item.operation in {"conflict", "not_found", "invalid"}:
            errors.extend(item.messages)
        operations.append(item)
    return PlanImportPreview(valid=not errors, operations=operations, errors=errors, warnings=_dedupe_preserve_order(warnings))


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


def _resolve_target_for_verify(
    db: Session,
    athlete_id: int,
    session_in: PlanImportSession,
) -> tuple[PlannedSession | None, str | None]:
    if session_in.session_id is not None:
        target = db.scalar(
            select(PlannedSession)
            .where(PlannedSession.id == session_in.session_id, PlannedSession.athlete_id == athlete_id)
            .options(selectinload(PlannedSession.training_day), selectinload(PlannedSession.planned_session_steps))
        )
        if target is None:
            return None, "SESSION_ID inexistente para este atleta."
        return target, None

    matches = _find_sessions_by_date_sport(db, athlete_id, session_in.date, session_in.sport)
    if not matches:
        return None, "No se encontro sesion para DATE + SPORT."
    if len(matches) == 1:
        return matches[0], None
    if session_in.name:
        exact_name_matches = [
            item for item in matches
            if (item.name or "").strip().casefold() == session_in.name.strip().casefold()
        ]
        if len(exact_name_matches) == 1:
            return exact_name_matches[0], None
        if len(exact_name_matches) > 1:
            return None, "Hay multiples coincidencias para DATE + SPORT + NAME."
    return None, "Hay multiples coincidencias para DATE + SPORT."


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


def _find_extra_sessions_in_window(
    db: Session,
    *,
    athlete_id: int,
    week_start_date: date,
    week_end_date: date,
    matched_session_ids: set[int],
) -> list[PlannedSession]:
    sessions = list(
        db.scalars(
            select(PlannedSession)
            .join(TrainingDay, PlannedSession.training_day_id == TrainingDay.id)
            .where(
                PlannedSession.athlete_id == athlete_id,
                TrainingDay.day_date >= week_start_date,
                TrainingDay.day_date <= week_end_date,
            )
            .options(selectinload(PlannedSession.training_day), selectinload(PlannedSession.planned_session_steps))
            .order_by(TrainingDay.day_date.asc(), PlannedSession.session_order.asc(), PlannedSession.id.asc())
        ).all()
    )
    return [item for item in sessions if item.id not in matched_session_ids]


def _create_session(db: Session, athlete_id: int, session_in: PlanImportSession) -> PlannedSession:
    training_day = _get_or_create_training_day(db, athlete_id, session_in.date, session_in.sport)
    session_order = _next_session_order(db, training_day.id)
    session = PlannedSession(
        athlete_id=athlete_id,
        training_day_id=training_day.id,
        sport_type=session_in.sport,
        session_type=session_in.session_type,
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
    if session_in.session_type is not None:
        session.session_type = session_in.session_type
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
        "warnings": [],
        "affected_session_ids": [],
    }


def _normalize_imported_session_type(session_in: PlanImportSession) -> list[str]:
    if session_in.session_type:
        return []
    notes = (session_in.notes or "").strip().lower()
    if "opcional" in notes or "optional" in notes:
        session_in.session_type = "optional"
        return ["Se detecto opcional por notas; se recomienda usar SESSION_TYPE: optional."]
    session_in.session_type = "required"
    return []


def _resolve_verify_window(payload: PlanImportPayload) -> tuple[date, date]:
    if payload.start_date and payload.end_date:
        return payload.start_date, payload.end_date
    session_dates = sorted(item.date for item in payload.sessions if item.date is not None)
    if not session_dates:
        raise ValueError("El bloque importable no tiene fechas suficientes para verificar.")
    if len(session_dates) == 1:
        target_date = session_dates[0]
        start_date = target_date - timedelta(days=target_date.weekday())
        end_date = start_date + timedelta(days=6)
        return start_date, end_date
    return session_dates[0], session_dates[-1]


def _serialize_expected_import_session(session_in: PlanImportSession) -> dict[str, Any]:
    return {
        "session_id": session_in.session_id,
        "date": session_in.date.isoformat() if session_in.date else None,
        "sport": session_in.sport,
        "name": session_in.name,
        "modality": session_in.modality,
        "session_type": session_in.session_type,
        "duration_minutes": _import_session_duration_minutes(session_in),
        "blocks_count": len(session_in.blocks),
    }


def _serialize_actual_verify_session(session: PlannedSession) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "date": session.training_day.day_date.isoformat() if session.training_day and session.training_day.day_date else None,
        "sport": session.sport_type,
        "name": session.name,
        "modality": session.modality,
        "session_type": _normalize_actual_session_type(session),
        "duration_minutes": _actual_session_duration_minutes(session),
        "blocks_count": len(session.planned_session_steps),
        "completion_source": session.completion_source,
    }


def _compare_verify_session_fields(session_in: PlanImportSession, session: PlannedSession) -> list[str]:
    differences: list[str] = []
    actual_date = session.training_day.day_date if session.training_day is not None else None
    if session_in.date != actual_date:
        differences.append("date")
    if (session_in.sport or None) != (session.sport_type or None):
        differences.append("sport")
    if session_in.action != "cancel":
        if (session_in.name or None) != (session.name or None):
            differences.append("name")
        if (session_in.modality or None) != (session.modality or None):
            differences.append("modality")
        if (session_in.session_type or "required") != _normalize_actual_session_type(session):
            differences.append("session_type")
        if _import_session_duration_minutes(session_in) != _actual_session_duration_minutes(session):
            differences.append("duration_minutes")
        if len(session_in.blocks) != len(session.planned_session_steps):
            differences.append("blocks_count")
    elif (session.completion_source or "").strip().lower() not in {"cancelled", "canceled"}:
        differences.append("completion_source")
    return differences


def _import_session_duration_minutes(session_in: PlanImportSession) -> int:
    duration_min = 0
    for block in session_in.blocks:
        unit = (block.unit or "").strip().lower()
        if block.value is None:
            continue
        if unit in {"min", "minute", "minutes"}:
            duration_min += int(round(block.value))
        elif unit in {"sec", "second", "seconds"}:
            duration_min += int(round(block.value / 60))
    return duration_min


def _actual_session_duration_minutes(session: PlannedSession) -> int:
    if session.planned_session_steps:
        total_sec = sum(int(step.duration_sec or 0) for step in session.planned_session_steps)
        if total_sec > 0:
            return int(round(total_sec / 60))
    return int(session.expected_duration_min or 0)


def _normalize_actual_session_type(session: PlannedSession) -> str:
    session_type = (session.session_type or "").strip().lower()
    if session_type in {"required", "optional", "recovery", "race", "test"}:
        return session_type
    text = " ".join(
        str(item).lower()
        for item in (session.name, session.target_notes, session.description_text)
        if item
    )
    if "opcional" in text or "optional" in text:
        return "optional"
    return "required"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
