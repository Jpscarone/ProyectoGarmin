from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


SPORT_PATTERNS = [
    (r"^mtb$", ("mtb", "mountain")),
    (r"^(running|run)$", ("running", "street")),
    (r"^(ciclismo|bici|bike)$", ("cycling", "road")),
    (r"^(natacion|swimming)$", ("swimming", "pool")),
    (r"^(trail)$", ("trail_running", "trail")),
]

SPORT_HINTS = [
    (r"\bmtb\b", ("mtb", "mountain")),
    (r"\b(ciclismo|bici|bike)\b", ("cycling", "road")),
    (r"\btrail\b", ("trail_running", "trail")),
    (r"\b(running|run|trote|rodaje)\b", ("running", "street")),
    (r"\b(natacion|pileta|swimming)\b", ("swimming", "pool")),
    (r"\baguas abiertas\b|\bopen water\b", ("swimming", "open_water")),
]

INTENSITY_LABEL_PATTERNS = [
    (r"\bz([1-5])\b", lambda match: f"Z{match.group(1)}"),
    (r"\britmo\s*5k\b", lambda _: "ritmo 5k"),
    (r"\britmo\s*10k\b", lambda _: "ritmo 10k"),
    (r"\bumbral\b", lambda _: "umbral"),
    (r"\btempo\b", lambda _: "tempo"),
    (r"\bfondo\b", lambda _: "fondo"),
    (r"\btecnica\b", lambda _: "tecnica"),
    (r"\bregenerativ[oa]?\b|\brecuperacion\b|\brecuperativo\b", lambda _: "recuperacion"),
    (r"\bcontinu[oa]s?\b", lambda _: "base"),
    (r"\bbase\b", lambda _: "base"),
    (r"\bfuerte(?:s)?\b|\bduro(?:s)?\b", lambda _: "fuerte"),
    (r"\bsuave(?:s)?\b", lambda _: "suave"),
    (r"\benfriar\b|\benfriamiento\b|\bafloje\b", lambda _: "enfriar"),
    (r"\brecuperacion\b|\brecuperar\b|\bpausa\b|\bdescanso\b", lambda _: "recuperacion"),
]

SESSION_TYPE_FROM_INTENSITY = {
    "suave": "easy",
    "enfriar": "easy",
    "base": "base",
    "fondo": "long",
    "tempo": "tempo",
    "fuerte": "hard",
    "umbral": "tempo",
    "tecnica": "technique",
    "recuperacion": "recovery",
}


class SessionParseError(ValueError):
    pass


@dataclass
class ParsedStep:
    step_order: int
    step_type: str
    repeat_count: int | None = None
    duration_sec: int | None = None
    distance_m: int | None = None
    target_notes: str | None = None


@dataclass
class ParsedSessionPlan:
    name: str
    sport_type: str | None
    discipline_variant: str | None
    session_type: str | None
    expected_duration_min: int | None
    expected_distance_km: float | None
    target_hr_zone: str | None
    target_power_zone: str | None
    target_notes: str | None
    description_text: str
    steps: list[ParsedStep]
    parse_confidence: str


@dataclass
class StructuredSimpleBlock:
    type: Literal["simple"]
    raw_text: str
    duration_type: Literal["time", "distance"]
    duration_value: float
    duration_unit: str
    intensity_label: str | None
    step_type: str
    duration_sec: int | None
    distance_m: int | None


@dataclass
class StructuredRepeatBlock:
    type: Literal["repeat"]
    raw_text: str
    repeat_count: int
    steps: list[StructuredSimpleBlock]


StructuredBlock = StructuredSimpleBlock | StructuredRepeatBlock


@dataclass
class StructuredParsedSession:
    sport: str | None
    discipline_variant: str | None
    raw_input: str
    steps: list[StructuredBlock]


def parse_session_text(text: str, fallback_sport_type: str | None = None) -> ParsedSessionPlan:
    structured = parse_standardized_session_text(text, fallback_sport_type=fallback_sport_type)
    return _structured_session_to_plan(structured)


def parse_session_text_to_json(text: str, fallback_sport_type: str | None = None) -> dict[str, object]:
    structured = parse_standardized_session_text(text, fallback_sport_type=fallback_sport_type)
    return structured_session_to_dict(structured)


def parse_standardized_session_text(text: str, fallback_sport_type: str | None = None) -> StructuredParsedSession:
    raw = text.strip()
    if not raw:
        raise SessionParseError("La sesion no puede estar vacia.")

    _validate_parentheses(raw)
    normalized = _normalize_text(raw)
    top_level_parts = _split_top_level_blocks(raw)
    if not top_level_parts:
        raise SessionParseError("No se encontraron bloques validos. Usa '+' para separar bloques.")

    sport_type, discipline_variant, remaining_parts = _extract_sport_prefix(top_level_parts, fallback_sport_type)
    if not remaining_parts:
        raise SessionParseError("Falta la estructura de la sesion despues del deporte.")

    structured_steps: list[StructuredBlock] = []
    for part in remaining_parts:
        structured_steps.append(_parse_block(part))

    if not structured_steps:
        raise SessionParseError(_format_suggestion("No se pudo interpretar ningun bloque de la sesion."))

    if sport_type is None:
        sport_type, discipline_variant = _detect_sport_from_text(normalized)

    return StructuredParsedSession(
        sport=sport_type,
        discipline_variant=discipline_variant,
        raw_input=raw,
        steps=structured_steps,
    )


def structured_session_to_dict(parsed: StructuredParsedSession) -> dict[str, object]:
    return {
        "sport": parsed.sport,
        "discipline_variant": parsed.discipline_variant,
        "raw_input": parsed.raw_input,
        "steps": [_structured_block_to_dict(step) for step in parsed.steps],
    }


def _structured_block_to_dict(step: StructuredBlock) -> dict[str, object]:
    if isinstance(step, StructuredRepeatBlock):
        return {
            "type": "repeat",
            "raw_text": step.raw_text,
            "repeat_count": step.repeat_count,
            "steps": [_structured_block_to_dict(inner_step) for inner_step in step.steps],
        }

    return {
        "type": "simple",
        "raw_text": step.raw_text,
        "duration_type": step.duration_type,
        "duration_value": step.duration_value,
        "duration_unit": step.duration_unit,
        "intensity_label": step.intensity_label,
        "step_type": step.step_type,
        "duration_sec": step.duration_sec,
        "distance_m": step.distance_m,
    }


def _structured_session_to_plan(parsed: StructuredParsedSession) -> ParsedSessionPlan:
    flat_steps = _flatten_structured_steps(parsed.steps)
    expected_duration_min = _structured_duration_minutes(parsed.steps)
    expected_distance_km = _structured_distance_km(parsed.steps)
    target_hr_zone = _first_zone_label(parsed.steps)
    session_type = _detect_session_type_from_structure(parsed.steps)
    target_notes = _build_target_notes_from_structure(parsed)

    should_persist_steps = _should_persist_steps(parsed.steps)
    steps = flat_steps if should_persist_steps else []

    return ParsedSessionPlan(
        name=_build_session_name(parsed.sport, parsed.steps, session_type, expected_duration_min, expected_distance_km, parsed.raw_input),
        sport_type=parsed.sport,
        discipline_variant=parsed.discipline_variant,
        session_type=session_type,
        expected_duration_min=expected_duration_min,
        expected_distance_km=expected_distance_km,
        target_hr_zone=target_hr_zone,
        target_power_zone=None,
        target_notes=target_notes,
        description_text=parsed.raw_input,
        steps=steps,
        parse_confidence="high" if should_persist_steps else "medium",
    )


def _validate_parentheses(text: str) -> None:
    balance = 0
    for char in text:
        if char == "(":
            balance += 1
        elif char == ")":
            balance -= 1
        if balance < 0:
            raise SessionParseError("Los parentesis estan desbalanceados.")
    if balance != 0:
        raise SessionParseError("Los parentesis estan desbalanceados.")


def _split_top_level_blocks(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0

    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "+" and depth == 0:
            part = "".join(current).strip()
            if not part:
                raise SessionParseError(_format_suggestion("Hay un bloque vacio alrededor de '+'."))
            parts.append(part)
            current = []
            continue
        current.append(char)

    final_part = "".join(current).strip()
    if not final_part:
        raise SessionParseError(_format_suggestion("La sesion termina con un bloque vacio."))
    parts.append(final_part)
    return parts


def _extract_sport_prefix(parts: list[str], fallback_sport_type: str | None) -> tuple[str | None, str | None, list[str]]:
    first_part_normalized = _normalize_text(parts[0])
    for pattern, result in SPORT_PATTERNS:
        if re.match(pattern, first_part_normalized):
            return result[0], result[1], parts[1:]
    if fallback_sport_type:
        return fallback_sport_type, None, parts
    return None, None, parts


def _detect_sport_from_text(normalized: str) -> tuple[str | None, str | None]:
    for pattern, result in SPORT_HINTS:
        if re.search(pattern, normalized):
            return result
    return None, None


def _parse_block(text: str) -> StructuredBlock:
    block = text.strip()
    if not block:
        raise SessionParseError(_format_suggestion("Hay un bloque vacio en la sesion."))

    repeat_match = re.match(r"^\s*(\d+)\s*x\s*\((.*)\)\s*$", block, re.IGNORECASE)
    if repeat_match:
        repeat_count = int(repeat_match.group(1))
        inner_content = repeat_match.group(2).strip()
        if not inner_content:
            raise SessionParseError("La repeticion no tiene contenido. Ejemplo valido: 5x(2min fuerte + 2min suave)")
        nested_parts = _split_top_level_blocks(inner_content)
        nested_steps = [_parse_simple_block(part) for part in nested_parts]
        return StructuredRepeatBlock(
            type="repeat",
            raw_text=block,
            repeat_count=repeat_count,
            steps=nested_steps,
        )

    natural_repeat = _parse_natural_repeat_block(block)
    if natural_repeat is not None:
        return natural_repeat

    if re.search(r"\b\d+\s*x\s*[^(]", _normalize_text(block)):
        normalized = _normalize_text(block)
        if " con " not in normalized and " rec " not in normalized and " pausa" not in normalized and " recuper" not in normalized:
            raise SessionParseError(
                "Formato de repeticion invalido. Usa Nx(...), por ejemplo: 5x(2min fuerte + 2min suave)"
            )

    return _parse_simple_block(block)


def _parse_simple_block(text: str) -> StructuredSimpleBlock:
    normalized = _normalize_text(text)
    measurement = _extract_measurement(normalized)
    if measurement is None:
        raise SessionParseError(
            _format_suggestion(
                f"No pude identificar duracion ni distancia en el bloque '{text.strip()}'."
            )
        )

    intensity_label = _extract_intensity_label(normalized)
    step_type = _infer_step_type(normalized, intensity_label)

    if measurement["kind"] == "time":
        return StructuredSimpleBlock(
            type="simple",
            raw_text=text.strip(),
            duration_type="time",
            duration_value=measurement["value"],
            duration_unit=measurement["unit"],
            intensity_label=intensity_label,
            step_type=step_type,
            duration_sec=measurement["seconds"],
            distance_m=None,
        )

    return StructuredSimpleBlock(
        type="simple",
        raw_text=text.strip(),
        duration_type="distance",
        duration_value=measurement["value"],
        duration_unit=measurement["unit"],
        intensity_label=intensity_label,
        step_type=step_type,
        duration_sec=None,
        distance_m=measurement["meters"],
    )


def _parse_natural_repeat_block(text: str) -> StructuredRepeatBlock | None:
    normalized = _normalize_text(text)
    match = re.match(
        r"^\s*(\d+)\s*x\s*(.+?)\s+(?:con|c\/|rec|recuperacion|recuperar|pausa|descanso|entre cada (?:uno|una))\s+(.+?)\s*$",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return None

    repeat_count = int(match.group(1))
    work_text = match.group(2).strip()
    recovery_text = match.group(3).strip()
    if not work_text or not recovery_text:
        raise SessionParseError("La repeticion no tiene bloques validos de trabajo y recuperacion.")

    work_step = _parse_simple_block(work_text)
    recovery_step = _parse_simple_block(recovery_text)
    recovery_step.step_type = "recovery"
    return StructuredRepeatBlock(
        type="repeat",
        raw_text=text.strip(),
        repeat_count=repeat_count,
        steps=[work_step, recovery_step],
    )


def _extract_measurement(normalized: str) -> dict[str, object] | None:
    pace_like = re.search(r"\b(\d+):(\d{2})h\b", normalized)
    if pace_like:
        hours = int(pace_like.group(1))
        minutes = int(pace_like.group(2))
        return {
            "kind": "time",
            "value": hours * 60 + minutes,
            "unit": "min",
            "seconds": hours * 3600 + minutes * 60,
        }

    compact_hhmm = re.search(r"\b(\d+)h(\d{1,2})\b", normalized)
    if compact_hhmm:
        hours = int(compact_hhmm.group(1))
        minutes = int(compact_hhmm.group(2))
        return {
            "kind": "time",
            "value": hours * 60 + minutes,
            "unit": "min",
            "seconds": hours * 3600 + minutes * 60,
        }

    spaced_hhmm = re.search(r"\b(\d+)\s*h(?:s|ora|horas)?\s*(\d{1,2})\b", normalized)
    if spaced_hhmm:
        hours = int(spaced_hhmm.group(1))
        minutes = int(spaced_hhmm.group(2))
        return {
            "kind": "time",
            "value": hours * 60 + minutes,
            "unit": "min",
            "seconds": hours * 3600 + minutes * 60,
        }

    hours_only = re.search(r"\b(\d+(?:[.,]\d+)?)\s*h(?:s|ora|horas)?\b", normalized)
    if hours_only:
        hours = float(hours_only.group(1).replace(",", "."))
        return {
            "kind": "time",
            "value": round(hours * 60, 2),
            "unit": "min",
            "seconds": int(round(hours * 3600)),
        }

    colon_time = re.search(r"\b(\d+):(\d{2})\b", normalized)
    if colon_time:
        minutes = int(colon_time.group(1))
        seconds = int(colon_time.group(2))
        return {
            "kind": "time",
            "value": round((minutes * 60 + seconds) / 60, 2),
            "unit": "seg",
            "seconds": minutes * 60 + seconds,
        }

    apostrophe_minutes = re.search(r"\b(\d+(?:[.,]\d+)?)\s*'\b", normalized)
    if apostrophe_minutes:
        value = float(apostrophe_minutes.group(1).replace(",", "."))
        return {
            "kind": "time",
            "value": value,
            "unit": "min",
            "seconds": int(round(value * 60)),
        }

    minutes = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(min\w*|mins|minuto|minutos)\b", normalized)
    if minutes:
        value = float(minutes.group(1).replace(",", "."))
        return {
            "kind": "time",
            "value": value,
            "unit": "min",
            "seconds": int(round(value * 60)),
        }

    seconds = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(s|seg|segundos)\b", normalized)
    if seconds:
        value = float(seconds.group(1).replace(",", "."))
        return {
            "kind": "time",
            "value": value,
            "unit": "seg",
            "seconds": int(round(value)),
        }

    kilometers = re.search(r"\b(\d+(?:[.,]\d+)?)\s*km\b", normalized)
    if kilometers:
        value = float(kilometers.group(1).replace(",", "."))
        return {
            "kind": "distance",
            "value": value,
            "unit": "km",
            "meters": int(round(value * 1000)),
        }

    shorthand_m = re.search(r"\b(\d+(?:[.,]\d+)?)\s*m\b", normalized)
    if shorthand_m:
        value = float(shorthand_m.group(1).replace(",", "."))
        if value >= 100:
            return {
                "kind": "distance",
                "value": value,
                "unit": "m",
                "meters": int(round(value)),
            }
        return {
            "kind": "time",
            "value": value,
            "unit": "min",
            "seconds": int(round(value * 60)),
        }

    return None


def _looks_like_minutes_shorthand(normalized: str) -> bool:
    return any(
        token in normalized
        for token in ("suave", "fuerte", "tempo", "enfriar", "afloje", "z1", "z2", "z3", "z4", "z5", "umbral")
    )


def _extract_intensity_label(normalized: str) -> str | None:
    for pattern, builder in INTENSITY_LABEL_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            return builder(match)
    return None


def _infer_step_type(normalized: str, intensity_label: str | None) -> str:
    if any(token in normalized for token in ("calentamiento", "entrada en calor")):
        return "warmup"
    if any(token in normalized for token in ("enfriar", "enfriamiento", "afloje", "vuelta a la calma")):
        return "cooldown"
    if any(token in normalized for token in ("recuperacion", "recuperar", "pausa", "descanso")):
        return "recovery"
    if "transicion" in normalized:
        return "transition"
    if "tecnica" in normalized:
        return "drills"
    if "strides" in normalized:
        return "strides"
    if "repeticion" in normalized and any(token in normalized for token in ("m", "km")):
        return "swim_repeat"
    if intensity_label in {"fuerte", "tempo", "umbral", "ritmo 5k", "ritmo 10k", "Z3", "Z4", "Z5"}:
        return "work"
    return "steady"


def _flatten_structured_steps(steps: list[StructuredBlock]) -> list[ParsedStep]:
    flat_steps: list[ParsedStep] = []
    step_order = 1

    for index, step in enumerate(steps):
        if isinstance(step, StructuredRepeatBlock):
            for nested_step in step.steps:
                flat_steps.append(
                    ParsedStep(
                        step_order=step_order,
                        step_type=_finalize_step_type(
                            nested_step.step_type,
                            nested_step.intensity_label,
                            is_first=index == 0 and nested_step == step.steps[0],
                            is_last=index == len(steps) - 1 and nested_step == step.steps[-1],
                        ),
                        repeat_count=step.repeat_count,
                        duration_sec=nested_step.duration_sec,
                        distance_m=nested_step.distance_m,
                        target_notes=nested_step.intensity_label or nested_step.raw_text,
                    )
                )
                step_order += 1
            continue

        flat_steps.append(
            ParsedStep(
                step_order=step_order,
                step_type=_finalize_step_type(
                    step.step_type,
                    step.intensity_label,
                    is_first=index == 0,
                    is_last=index == len(steps) - 1,
                ),
                repeat_count=None,
                duration_sec=step.duration_sec,
                distance_m=step.distance_m,
                target_notes=step.intensity_label or step.raw_text,
            )
        )
        step_order += 1

    return flat_steps


def _finalize_step_type(step_type: str, intensity_label: str | None, *, is_first: bool, is_last: bool) -> str:
    if step_type in {"warmup", "cooldown", "recovery", "transition", "drills"}:
        return step_type
    if is_first and intensity_label in {None, "suave", "base", "Z1", "Z2"}:
        return "warmup"
    if is_last and intensity_label in {None, "suave", "base", "enfriar", "afloje", "Z1", "Z2"}:
        return "cooldown"
    if intensity_label in {"suave", "base", "Z1", "Z2"}:
        return "steady"
    return step_type


def _structured_duration_minutes(steps: list[StructuredBlock]) -> int | None:
    total_seconds = 0
    has_primary_duration = False

    for step in steps:
        if isinstance(step, StructuredRepeatBlock):
            repeat_duration = _repeat_duration_seconds(step)
            if repeat_duration is None:
                return None
            total_seconds += repeat_duration
            if any(nested_step.step_type != "recovery" for nested_step in step.steps):
                has_primary_duration = True
            continue

        if step.duration_sec is None:
            return None
        total_seconds += step.duration_sec
        if step.step_type != "recovery":
            has_primary_duration = True

    if total_seconds == 0 or not has_primary_duration:
        return None
    return int(round(total_seconds / 60))


def _repeat_duration_seconds(step: StructuredRepeatBlock) -> int | None:
    nested_total = 0
    has_primary_duration = False
    for nested_step in step.steps:
        if nested_step.duration_sec is None:
            return None
        nested_total += nested_step.duration_sec
        if nested_step.step_type != "recovery":
            has_primary_duration = True
    if nested_total == 0 or not has_primary_duration:
        return None
    return nested_total * step.repeat_count


def _structured_distance_km(steps: list[StructuredBlock]) -> float | None:
    total_meters = 0
    has_distance = False

    for step in steps:
        if isinstance(step, StructuredRepeatBlock):
            nested_distance = _repeat_distance_meters(step)
            if nested_distance is not None:
                total_meters += nested_distance
                has_distance = True
            continue

        if step.distance_m is None:
            continue
        total_meters += step.distance_m
        has_distance = True

    if not has_distance:
        return None
    return round(total_meters / 1000, 2)


def _repeat_distance_meters(step: StructuredRepeatBlock) -> int | None:
    nested_distance = 0
    has_distance = False
    for nested_step in step.steps:
        if nested_step.distance_m is None:
            continue
        nested_distance += nested_step.distance_m
        has_distance = True
    if not has_distance:
        return None
    return nested_distance * step.repeat_count


def _first_zone_label(steps: list[StructuredBlock]) -> str | None:
    for step in steps:
        if isinstance(step, StructuredRepeatBlock):
            for nested_step in step.steps:
                if nested_step.intensity_label and nested_step.intensity_label.startswith("Z"):
                    return nested_step.intensity_label
            continue
        if step.intensity_label and step.intensity_label.startswith("Z"):
            return step.intensity_label
    return None


def _detect_session_type_from_structure(steps: list[StructuredBlock]) -> str | None:
    if any(isinstance(step, StructuredRepeatBlock) for step in steps):
        return "intervals"

    for step in steps:
        if isinstance(step, StructuredRepeatBlock):
            continue
        if step.intensity_label in SESSION_TYPE_FROM_INTENSITY:
            return SESSION_TYPE_FROM_INTENSITY[step.intensity_label]
        if step.intensity_label == "Z2":
            return "base"
        if step.intensity_label in {"Z4", "Z5"}:
            return "hard"
        if step.intensity_label == "Z3":
            return "tempo"
    return None


def _build_target_notes_from_structure(parsed: StructuredParsedSession) -> str | None:
    notes: list[str] = []
    for step in parsed.steps:
        if isinstance(step, StructuredRepeatBlock):
            notes.append(f"{step.repeat_count}x bloque")
            continue
        if step.intensity_label:
            notes.append(step.intensity_label)
    if notes:
        return ", ".join(dict.fromkeys(notes))
    return parsed.raw_input


def _should_persist_steps(steps: list[StructuredBlock]) -> bool:
    if len(steps) != 1:
        return True
    return isinstance(steps[0], StructuredRepeatBlock)


def _build_session_name(
    sport_type: str | None,
    steps: list[StructuredBlock],
    session_type: str | None,
    expected_duration_min: int | None,
    expected_distance_km: float | None,
    raw: str,
) -> str:
    sport_label = {
        "cycling": "Bici",
        "mtb": "MTB",
        "running": "Running",
        "trail_running": "Trail",
        "swimming": "Natacion",
        "multisport": "Multideporte",
    }.get(sport_type, "")
    type_label = {
        "easy": "suave",
        "base": "base",
        "tempo": "tempo",
        "long": "fondo",
        "hard": "fuerte",
        "intervals": "intervalos",
        "technique": "tecnica",
        "race": "competencia",
        "recovery": "recuperacion",
    }.get(session_type, "")

    main_block_label = _main_block_title_fragment(steps)
    pieces = [piece for piece in (sport_label, main_block_label or type_label) if piece]
    if main_block_label is None:
        if expected_duration_min is not None:
            pieces.append(f"{expected_duration_min} min")
        elif expected_distance_km is not None:
            pieces.append(f"{expected_distance_km:g} km")

    title = " ".join(pieces).strip()
    if title:
        return title[0].upper() + title[1:]
    return raw[:80]


def _main_block_title_fragment(steps: list[StructuredBlock]) -> str | None:
    repeat_blocks = [step for step in steps if isinstance(step, StructuredRepeatBlock)]
    if repeat_blocks:
        main_repeat = repeat_blocks[0]
        main_work = next((step for step in main_repeat.steps if step.step_type == "work"), main_repeat.steps[0])
        work_measurement = _measurement_label(main_work)
        recovery_step = next((step for step in main_repeat.steps if step.step_type == "recovery"), None)
        if recovery_step is None and len(main_repeat.steps) > 1:
            recovery_step = next((step for step in main_repeat.steps if step is not main_work), None)
        work_intensity = _title_intensity_label(main_work.intensity_label)
        if recovery_step is not None:
            recovery_measurement = _measurement_label(recovery_step)
            recovery_intensity = _title_intensity_label(recovery_step.intensity_label)
            recovery_fragment = " ".join(
                part for part in (recovery_measurement, recovery_intensity) if part
            ).strip()
            work_fragment = " ".join(
                part for part in (work_measurement, work_intensity) if part
            ).strip()
            return f"{main_repeat.repeat_count}x({work_fragment} + {recovery_fragment})"

        suffix = f" {work_intensity}" if work_intensity else ""
        return f"{main_repeat.repeat_count}x{work_measurement}{suffix}".strip()

    meaningful_simple_steps = [
        step
        for step in steps
        if isinstance(step, StructuredSimpleBlock) and step.step_type not in {"warmup", "cooldown", "recovery"}
    ]
    if meaningful_simple_steps:
        main_step = meaningful_simple_steps[0]
    elif steps and isinstance(steps[0], StructuredSimpleBlock):
        main_step = steps[0]
    else:
        return None

    measurement = _measurement_label(main_step)
    intensity = _title_intensity_label(main_step.intensity_label)
    return " ".join(part for part in (measurement, intensity) if part).strip() or None


def _measurement_label(step: StructuredSimpleBlock) -> str:
    if step.duration_type == "distance":
        if step.duration_unit == "km":
            return f"{step.duration_value:g}km"
        return f"{int(step.duration_value)}m"

    if step.duration_unit == "seg":
        seconds = int(step.duration_sec or 0)
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        remainder = seconds % 60
        if remainder == 0:
            return f"{minutes}min"
        return f"{minutes}:{remainder:02d}"

    total_seconds = int(step.duration_sec or 0)
    if total_seconds >= 3600:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if minutes:
            return f"{hours}h{minutes:02d}"
        return f"{hours}h"
    return f"{int(round(total_seconds / 60))}min"


def _title_intensity_label(intensity_label: str | None) -> str:
    if intensity_label is None:
        return ""
    labels = {
        "enfriar": "suave",
        "recuperacion": "suave",
    }
    return labels.get(intensity_label, intensity_label)


def _normalize_text(text: str) -> str:
    normalized = text.lower()
    mojibake_replacements = {
        "Ã¡": "a",
        "Ã©": "e",
        "Ã­": "i",
        "Ã³": "o",
        "Ãº": "u",
        "Ã±": "n",
    }
    for source, target in mojibake_replacements.items():
        normalized = normalized.replace(source, target)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.split())


def _format_suggestion(message: str) -> str:
    return (
        f"{message} Sugerencia: usa '+' para separar bloques, por ejemplo: "
        "10min suave + 5x(2min fuerte + 2min suave) + 10min suave"
    )
