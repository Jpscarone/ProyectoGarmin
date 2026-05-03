from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportError:
    line: int
    message: str


@dataclass
class ImportBlock:
    line: int
    value: str | None = None
    unit: str | None = None
    intensity: str | None = None
    zone: str | None = None
    hr_min: str | None = None
    hr_max: str | None = None
    pace_min: str | None = None
    pace_max: str | None = None
    power_min: str | None = None
    power_max: str | None = None
    rpe_min: str | None = None
    rpe_max: str | None = None
    notes: str | None = None


@dataclass
class ImportRepeat:
    line: int
    count: int | None = None
    blocks: list[ImportBlock] = field(default_factory=list)


@dataclass
class ImportSession:
    line: int
    date: str | None = None
    sport: str | None = None
    name: str | None = None
    notes: str | None = None
    blocks: list[ImportBlock | ImportRepeat] = field(default_factory=list)


@dataclass
class ImportGroup:
    line: int
    name: str | None = None
    date: str | None = None
    notes: str | None = None
    sessions: list[ImportSession] = field(default_factory=list)


@dataclass
class ImportParseResult:
    sessions: list[ImportSession]
    groups: list[ImportGroup]
    errors: list[ImportError]


ENTITY_TOKENS = {
    "SESSION",
    "SESSION_GROUP",
    "BLOCK",
    "REPEAT",
    "END",
    "END_REPEAT",
    "END_GROUP",
}


def parse_session_import_text(raw_text: str) -> ImportParseResult:
    errors: list[ImportError] = []
    sessions: list[ImportSession] = []
    groups: list[ImportGroup] = []

    current_group: ImportGroup | None = None
    current_session: ImportSession | None = None
    current_repeat: ImportRepeat | None = None
    current_block: ImportBlock | None = None

    def push_error(line_no: int, message: str) -> None:
        errors.append(ImportError(line=line_no, message=message))

    def finalize_block() -> None:
        nonlocal current_block
        current_block = None

    def finalize_repeat() -> None:
        nonlocal current_repeat, current_block
        current_repeat = None
        current_block = None

    def finalize_session() -> None:
        nonlocal current_session, current_repeat, current_block
        if current_session is None:
            return
        if current_repeat is not None:
            push_error(current_repeat.line, "END sin END_REPEAT.")
        current_repeat = None
        current_block = None
        if current_group is not None:
            current_group.sessions.append(current_session)
        else:
            sessions.append(current_session)
        current_session = None

    def normalize_key(raw: str) -> str:
        return raw.strip().upper()

    lines = raw_text.splitlines()
    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper in ENTITY_TOKENS:
            if upper == "SESSION_GROUP":
                if current_session is not None:
                    push_error(index, "SESSION_GROUP dentro de SESSION sin END.")
                    finalize_session()
                if current_group is not None:
                    push_error(index, "SESSION_GROUP sin END_GROUP.")
                current_group = ImportGroup(line=index)
            elif upper == "END_GROUP":
                if current_group is None:
                    push_error(index, "END_GROUP sin SESSION_GROUP.")
                else:
                    if current_session is not None:
                        finalize_session()
                    groups.append(current_group)
                    current_group = None
            elif upper == "SESSION":
                if current_session is not None:
                    push_error(index, "SESSION sin END.")
                    finalize_session()
                current_session = ImportSession(line=index)
            elif upper == "END":
                if current_session is None:
                    push_error(index, "END sin SESSION.")
                else:
                    finalize_session()
            elif upper == "REPEAT":
                if current_session is None:
                    push_error(index, "REPEAT sin SESSION.")
                    continue
                if current_repeat is not None:
                    push_error(index, "REPEAT anidado no soportado.")
                    continue
                repeat_block = ImportRepeat(line=index)
                current_session.blocks.append(repeat_block)
                current_repeat = repeat_block
            elif upper == "END_REPEAT":
                if current_repeat is None:
                    push_error(index, "END_REPEAT sin REPEAT.")
                else:
                    finalize_repeat()
            elif upper == "BLOCK":
                if current_session is None:
                    push_error(index, "BLOCK sin SESSION.")
                    continue
                finalize_block()
                block = ImportBlock(line=index)
                if current_repeat is not None:
                    current_repeat.blocks.append(block)
                else:
                    current_session.blocks.append(block)
                current_block = block
            continue

        if ":" not in line:
            push_error(index, "Linea invalida. Se esperaba KEY: valor.")
            continue

        raw_key, raw_value = line.split(":", 1)
        key = normalize_key(raw_key)
        value = raw_value.strip()

        if current_block is not None and key in {
            "VALUE",
            "UNIT",
            "INTENSITY",
            "ZONE",
            "HR_MIN",
            "HR_MAX",
            "FC_MIN",
            "FC_MAX",
            "PACE_MIN",
            "PACE_MAX",
            "POWER_MIN",
            "POWER_MAX",
            "RPE_MIN",
            "RPE_MAX",
            "NOTES",
        }:
            if key == "VALUE":
                current_block.value = value
            elif key == "UNIT":
                current_block.unit = value
            elif key == "INTENSITY":
                current_block.intensity = value
            elif key == "ZONE":
                current_block.zone = value
            elif key in {"HR_MIN", "FC_MIN"}:
                current_block.hr_min = value
            elif key in {"HR_MAX", "FC_MAX"}:
                current_block.hr_max = value
            elif key == "PACE_MIN":
                current_block.pace_min = value
            elif key == "PACE_MAX":
                current_block.pace_max = value
            elif key == "POWER_MIN":
                current_block.power_min = value
            elif key == "POWER_MAX":
                current_block.power_max = value
            elif key == "RPE_MIN":
                current_block.rpe_min = value
            elif key == "RPE_MAX":
                current_block.rpe_max = value
            elif key == "NOTES":
                current_block.notes = value
            continue

        if current_repeat is not None and key == "COUNT":
            current_repeat.count = _parse_optional_int(value)
            continue

        if current_session is not None and key in {"DATE", "SPORT", "NAME", "NOTES"}:
            if key == "DATE":
                current_session.date = value
            elif key == "SPORT":
                current_session.sport = value
            elif key == "NAME":
                current_session.name = value
            elif key == "NOTES":
                current_session.notes = value
            continue

        if current_group is not None and key in {"DATE", "NAME", "NOTES"}:
            if key == "DATE":
                current_group.date = value
            elif key == "NAME":
                current_group.name = value
            elif key == "NOTES":
                current_group.notes = value
            continue

        push_error(index, f"Campo inesperado: {key}.")

    if current_session is not None:
        push_error(current_session.line, "END faltante para SESSION.")
        finalize_session()
    if current_group is not None:
        push_error(current_group.line, "END_GROUP faltante para SESSION_GROUP.")
        groups.append(current_group)

    return ImportParseResult(sessions=sessions, groups=groups, errors=errors)


def _parse_optional_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed
