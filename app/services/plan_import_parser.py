from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


PlanImportAction = Literal["create", "update", "upsert", "cancel"]


class PlanImportParseError(ValueError):
    pass


@dataclass(slots=True)
class PlanImportBlock:
    value: float | None = None
    unit: str | None = None
    intensity: str | None = None
    zone: str | None = None
    rpe_min: int | None = None
    rpe_max: int | None = None
    hr_min: int | None = None
    hr_max: int | None = None
    pace_min: int | None = None
    pace_max: int | None = None
    notes: str | None = None


@dataclass(slots=True)
class PlanImportSession:
    action: PlanImportAction
    session_id: int | None = None
    date: date | None = None
    sport: str | None = None
    modality: str | None = None
    name: str | None = None
    notes: str | None = None
    reason: str | None = None
    blocks: list[PlanImportBlock] = field(default_factory=list)


@dataclass(slots=True)
class PlanImportPayload:
    start_date: date | None = None
    end_date: date | None = None
    mode: str | None = None
    sessions: list[PlanImportSession] = field(default_factory=list)


def parse_plan_import(import_text: str) -> PlanImportPayload:
    payload = PlanImportPayload()
    current_session: _SessionBuilder | None = None
    current_block: dict[str, str] | None = None
    saw_end = False

    for line_number, raw_line in enumerate((import_text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        marker = line.upper()
        if marker == "WEEK":
            _finish_block(current_session, current_block, line_number)
            current_block = None
            current_session = _finish_session(payload, current_session, line_number)
            continue
        if marker == "SESSION":
            _finish_block(current_session, current_block, line_number)
            current_block = None
            current_session = _finish_session(payload, current_session, line_number)
            current_session = _SessionBuilder(line_number=line_number)
            continue
        if marker == "BLOCK":
            if current_session is None:
                raise PlanImportParseError(f"Linea {line_number}: BLOCK debe estar dentro de SESSION.")
            _finish_block(current_session, current_block, line_number)
            current_block = {}
            continue
        if marker == "END":
            _finish_block(current_session, current_block, line_number)
            current_block = None
            current_session = _finish_session(payload, current_session, line_number)
            saw_end = True
            continue

        key, value = _parse_key_value(line, line_number)
        if current_block is not None:
            current_block[key] = value
        elif current_session is not None:
            current_session.fields[key] = value
        else:
            _apply_week_field(payload, key, value, line_number)

    if current_block is not None or current_session is not None:
        _finish_block(current_session, current_block, len((import_text or "").splitlines()))
        _finish_session(payload, current_session, len((import_text or "").splitlines()))

    if not saw_end:
        raise PlanImportParseError("El bloque debe finalizar con END.")
    if not payload.sessions:
        raise PlanImportParseError("El bloque no contiene sesiones.")
    if payload.start_date and payload.end_date and payload.start_date > payload.end_date:
        raise PlanImportParseError("START_DATE no puede ser posterior a END_DATE.")
    return payload


@dataclass(slots=True)
class _SessionBuilder:
    line_number: int
    fields: dict[str, str] = field(default_factory=dict)
    blocks: list[PlanImportBlock] = field(default_factory=list)


def _parse_key_value(line: str, line_number: int) -> tuple[str, str]:
    if ":" not in line:
        raise PlanImportParseError(f"Linea {line_number}: se esperaba KEY: value.")
    key, value = line.split(":", 1)
    normalized_key = key.strip().upper()
    if not normalized_key:
        raise PlanImportParseError(f"Linea {line_number}: clave vacia.")
    return normalized_key, value.strip()


def _apply_week_field(payload: PlanImportPayload, key: str, value: str, line_number: int) -> None:
    if key == "START_DATE":
        payload.start_date = _parse_date(value, key, line_number)
    elif key == "END_DATE":
        payload.end_date = _parse_date(value, key, line_number)
    elif key == "MODE":
        payload.mode = value.strip().lower() or None
    else:
        raise PlanImportParseError(f"Linea {line_number}: campo WEEK no soportado: {key}.")


def _finish_block(
    current_session: _SessionBuilder | None,
    current_block: dict[str, str] | None,
    line_number: int,
) -> None:
    if current_block is None:
        return
    if current_session is None:
        raise PlanImportParseError(f"Linea {line_number}: BLOCK sin SESSION.")
    allowed = {
        "VALUE",
        "UNIT",
        "INTENSITY",
        "ZONE",
        "RPE_MIN",
        "RPE_MAX",
        "HR_MIN",
        "HR_MAX",
        "PACE_MIN",
        "PACE_MAX",
        "NOTES",
    }
    _reject_unknown(current_block, allowed, "BLOCK", line_number)
    current_session.blocks.append(
        PlanImportBlock(
            value=_parse_float(current_block.get("VALUE"), "VALUE", line_number) if "VALUE" in current_block else None,
            unit=_optional_text(current_block.get("UNIT")),
            intensity=_optional_text(current_block.get("INTENSITY"), lower=True),
            zone=_optional_text(current_block.get("ZONE")),
            rpe_min=_parse_optional_int(current_block.get("RPE_MIN"), "RPE_MIN", line_number),
            rpe_max=_parse_optional_int(current_block.get("RPE_MAX"), "RPE_MAX", line_number),
            hr_min=_parse_optional_int(current_block.get("HR_MIN"), "HR_MIN", line_number),
            hr_max=_parse_optional_int(current_block.get("HR_MAX"), "HR_MAX", line_number),
            pace_min=_parse_optional_int(current_block.get("PACE_MIN"), "PACE_MIN", line_number),
            pace_max=_parse_optional_int(current_block.get("PACE_MAX"), "PACE_MAX", line_number),
            notes=_optional_text(current_block.get("NOTES")),
        )
    )


def _finish_session(
    payload: PlanImportPayload,
    current_session: _SessionBuilder | None,
    line_number: int,
) -> None:
    if current_session is None:
        return None
    fields = current_session.fields
    allowed = {"ACTION", "SESSION_ID", "DATE", "SPORT", "MODALITY", "NAME", "NOTES", "REASON"}
    _reject_unknown(fields, allowed, "SESSION", line_number)
    raw_action = (fields.get("ACTION") or "").strip().lower()
    if raw_action not in {"create", "update", "upsert", "cancel"}:
        raise PlanImportParseError(f"Linea {current_session.line_number}: ACTION debe ser create, update, upsert o cancel.")
    session = PlanImportSession(
        action=raw_action,  # type: ignore[arg-type]
        session_id=_parse_optional_int(fields.get("SESSION_ID"), "SESSION_ID", line_number),
        date=_parse_date(fields["DATE"], "DATE", line_number) if fields.get("DATE") else None,
        sport=_optional_text(fields.get("SPORT"), lower=True),
        modality=_optional_text(fields.get("MODALITY"), lower=True),
        name=_optional_text(fields.get("NAME")),
        notes=_optional_text(fields.get("NOTES")),
        reason=_optional_text(fields.get("REASON")),
        blocks=list(current_session.blocks),
    )
    _validate_session_required_fields(session, current_session.line_number)
    payload.sessions.append(session)
    return None


def _validate_session_required_fields(session: PlanImportSession, line_number: int) -> None:
    if session.session_id is None and session.date is None:
        raise PlanImportParseError(f"Linea {line_number}: DATE es obligatorio si no se usa SESSION_ID.")
    if session.action in {"create", "upsert"}:
        if session.date is None:
            raise PlanImportParseError(f"Linea {line_number}: DATE es obligatorio para {session.action}.")
        if not session.sport:
            raise PlanImportParseError(f"Linea {line_number}: SPORT es obligatorio para {session.action}.")
        if not session.name:
            raise PlanImportParseError(f"Linea {line_number}: NAME es obligatorio para {session.action}.")
    if session.action == "update" and session.session_id is None and not session.sport:
        raise PlanImportParseError(f"Linea {line_number}: SPORT es obligatorio para update sin SESSION_ID.")
    if session.action == "cancel" and session.session_id is None and not session.sport:
        raise PlanImportParseError(f"Linea {line_number}: SPORT es obligatorio para cancel sin SESSION_ID.")


def _reject_unknown(fields: dict[str, str], allowed: set[str], section: str, line_number: int) -> None:
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise PlanImportParseError(f"Linea {line_number}: campos {section} no soportados: {', '.join(unknown)}.")


def _parse_date(value: str, field_name: str, line_number: int) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise PlanImportParseError(f"Linea {line_number}: {field_name} debe tener formato YYYY-MM-DD.") from exc


def _parse_float(value: str | None, field_name: str, line_number: int) -> float:
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise PlanImportParseError(f"Linea {line_number}: {field_name} debe ser numerico.") from exc


def _parse_optional_int(value: str | None, field_name: str, line_number: int) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError as exc:
        raise PlanImportParseError(f"Linea {line_number}: {field_name} debe ser entero.") from exc


def _optional_text(value: str | None, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized.lower() if lower else normalized
