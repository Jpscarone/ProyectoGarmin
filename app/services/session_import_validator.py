from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from app.services.session_import_parser import (
    ImportBlock,
    ImportError,
    ImportGroup,
    ImportRepeat,
    ImportSession,
)


SUPPORTED_SPORTS = {"running", "cycling", "swimming", "strength", "walking", "other"}
SUPPORTED_INTENSITY = {"hr", "pace", "power", "rpe"}
SUPPORTED_UNITS = {"seg", "s", "sec", "min", "h", "m", "km"}
SUPPORTED_ZONES = {"z1", "z2", "z3", "z4", "z5", "custom"}
PACE_PATTERN = re.compile(r"^\s*(\d{1,2}):(\d{2})(?:\s*/\s*km)?\s*$", re.IGNORECASE)


@dataclass
class ImportValidationResult:
    errors: list[ImportError]


def validate_import_payload(
    *,
    sessions: list[ImportSession],
    groups: list[ImportGroup],
    base_date: date | None,
) -> ImportValidationResult:
    errors: list[ImportError] = []

    for group in groups:
        group_date = _parse_date(group.date, group.line, errors, field_name="DATE") if group.date else None
        if not group.name:
            errors.append(ImportError(line=group.line, message="SESSION_GROUP sin NAME."))
        for session in group.sessions:
            session_date = _parse_date(session.date, session.line, errors, field_name="DATE") if session.date else None
            if group_date and session_date and group_date != session_date:
                errors.append(
                    ImportError(
                        line=session.line,
                        message="SESSION dentro de SESSION_GROUP tiene DATE distinta al grupo.",
                    )
                )
            _validate_session(session, errors, base_date or group_date)

    for session in sessions:
        _validate_session(session, errors, base_date)

    return ImportValidationResult(errors=errors)


def _validate_session(session: ImportSession, errors: list[ImportError], fallback_date: date | None) -> None:
    if not session.sport:
        errors.append(ImportError(line=session.line, message="SPORT faltante en SESSION."))
    elif session.sport.strip().lower() not in SUPPORTED_SPORTS:
        errors.append(ImportError(line=session.line, message=f"SPORT invalido: {session.sport}."))

    if session.date:
        _parse_date(session.date, session.line, errors, field_name="DATE")
    elif fallback_date is None:
        errors.append(ImportError(line=session.line, message="DATE faltante en SESSION."))

    if not session.blocks:
        errors.append(ImportError(line=session.line, message="SESSION sin BLOCKS."))

    for block in session.blocks:
        if isinstance(block, ImportRepeat):
            _validate_repeat(block, errors)
        else:
            _validate_block(block, errors)


def _validate_repeat(repeat_block: ImportRepeat, errors: list[ImportError]) -> None:
    if repeat_block.count is None or repeat_block.count <= 0:
        errors.append(ImportError(line=repeat_block.line, message="COUNT invalido en REPEAT."))
    if not repeat_block.blocks:
        errors.append(ImportError(line=repeat_block.line, message="REPEAT sin BLOCKS."))
    for block in repeat_block.blocks:
        _validate_block(block, errors)


def _validate_block(block: ImportBlock, errors: list[ImportError]) -> None:
    intensity = block.intensity.strip().lower() if block.intensity else None
    zone = block.zone.strip().lower() if block.zone else None

    if not block.value:
        errors.append(ImportError(line=block.line, message="VALUE faltante en BLOCK."))
    if not block.unit:
        errors.append(ImportError(line=block.line, message="UNIT faltante en BLOCK."))
    elif block.unit.strip().lower() not in SUPPORTED_UNITS:
        errors.append(ImportError(line=block.line, message=f"UNIT invalido: {block.unit}."))

    if block.intensity and intensity not in SUPPORTED_INTENSITY:
        errors.append(ImportError(line=block.line, message=f"INTENSITY invalida: {block.intensity}."))

    if block.value and not _is_number(block.value):
        errors.append(ImportError(line=block.line, message=f"VALUE invalido: {block.value}."))

    if block.zone and zone not in SUPPORTED_ZONES:
        errors.append(ImportError(line=block.line, message=f"ZONE invalida: {block.zone}."))

    if zone == "custom":
        _validate_custom_block(block, intensity, errors)
    elif zone:
        _validate_non_custom_block(block, errors)


def _validate_custom_block(block: ImportBlock, intensity: str | None, errors: list[ImportError]) -> None:
    if intensity == "hr":
        minimum = _parse_number(block.hr_min)
        maximum = _parse_number(block.hr_max)
        if minimum is None or maximum is None:
            errors.append(ImportError(line=block.line, message="ZONE custom con INTENSITY hr requiere HR_MIN/HR_MAX o FC_MIN/FC_MAX validos."))
            return
        _validate_numeric_range(block.line, errors, minimum=minimum, maximum=maximum, minimum_allowed=40, maximum_allowed=220, label="HR")
        return

    if intensity == "pace":
        minimum = _parse_pace_seconds(block.pace_min)
        maximum = _parse_pace_seconds(block.pace_max)
        if minimum is None or maximum is None:
            errors.append(ImportError(line=block.line, message="ZONE custom con INTENSITY pace requiere PACE_MIN/PACE_MAX en formato mm:ss o mm:ss/km."))
            return
        _validate_numeric_range(block.line, errors, minimum=minimum, maximum=maximum, minimum_allowed=120, maximum_allowed=1800, label="PACE")
        return

    if intensity == "power":
        minimum = _parse_number(block.power_min)
        maximum = _parse_number(block.power_max)
        if minimum is None or maximum is None:
            errors.append(ImportError(line=block.line, message="ZONE custom con INTENSITY power requiere POWER_MIN/POWER_MAX validos."))
            return
        _validate_numeric_range(block.line, errors, minimum=minimum, maximum=maximum, minimum_allowed=1, maximum_allowed=3000, label="POWER")
        return

    if intensity == "rpe":
        minimum = _parse_number(block.rpe_min)
        maximum = _parse_number(block.rpe_max)
        if minimum is None or maximum is None:
            errors.append(ImportError(line=block.line, message="ZONE custom con INTENSITY rpe requiere RPE_MIN/RPE_MAX validos."))
            return
        _validate_numeric_range(block.line, errors, minimum=minimum, maximum=maximum, minimum_allowed=1, maximum_allowed=10, label="RPE")
        return

    errors.append(ImportError(line=block.line, message="ZONE custom requiere INTENSITY hr, pace, power o rpe."))


def _validate_non_custom_block(block: ImportBlock, errors: list[ImportError]) -> None:
    if any(
        value is not None and str(value).strip()
        for value in (
            block.hr_min,
            block.hr_max,
            block.pace_min,
            block.pace_max,
            block.power_min,
            block.power_max,
            block.rpe_min,
            block.rpe_max,
        )
    ):
        errors.append(ImportError(line=block.line, message="Campos custom no permitidos cuando ZONE no es custom."))


def _validate_numeric_range(
    line: int,
    errors: list[ImportError],
    *,
    minimum: float,
    maximum: float,
    minimum_allowed: float,
    maximum_allowed: float,
    label: str,
) -> None:
    if minimum >= maximum:
        errors.append(ImportError(line=line, message=f"{label}_MIN debe ser menor que {label}_MAX."))
    if minimum < minimum_allowed or maximum > maximum_allowed:
        errors.append(
            ImportError(
                line=line,
                message=f"Rango {label} fuera de limites razonables ({int(minimum_allowed)}-{int(maximum_allowed)}).",
            )
        )


def _parse_date(value: str | None, line: int, errors: list[ImportError], field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        errors.append(ImportError(line=line, message=f"{field_name} invalida: {value}."))
        return None


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", "."))
        return True
    except ValueError:
        return False


def _parse_number(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _parse_pace_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    match = PACE_PATTERN.fullmatch(value)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    if seconds > 59:
        return None
    return (minutes * 60) + seconds
