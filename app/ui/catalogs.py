from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Option:
    value: str
    label: str


SPORT_OPTIONS = [
    Option("cycling", "Ciclismo"),
    Option("mtb", "MTB"),
    Option("running", "Running"),
    Option("trail_running", "Trail running"),
    Option("swimming", "Natacion"),
    Option("multisport", "Multideporte"),
]

SPORT_LABELS = {
    "cycling": "Ciclismo",
    "road_cycling": "Ciclismo",
    "bike": "Ciclismo",
    "mtb": "MTB",
    "mountain_biking": "MTB",
    "running": "Running",
    "run": "Running",
    "trail_running": "Trail running",
    "trail_run": "Trail running",
    "swimming": "Natacion",
    "lap_swimming": "Natacion",
    "pool_swim": "Natacion",
    "multisport": "Multideporte",
}

VARIANT_OPTIONS = [
    Option("road", "Ruta"),
    Option("mountain", "Montana"),
    Option("street", "Calle"),
    Option("trail", "Trail"),
    Option("pool", "Pileta"),
    Option("open_water", "Aguas abiertas"),
]

VARIANT_LABELS = {
    "road": "Ruta",
    "mountain": "Montana",
    "mtb": "Montana",
    "street": "Calle",
    "trail": "Trail",
    "pool": "Pileta",
    "open_water": "Aguas abiertas",
}

SESSION_TYPE_OPTIONS = [
    Option("easy", "Suave"),
    Option("base", "Base"),
    Option("long", "Fondo"),
    Option("tempo", "Tempo"),
    Option("hard", "Fuerte"),
    Option("intervals", "Intervalos"),
    Option("technique", "Tecnica"),
    Option("race", "Competencia"),
    Option("recovery", "Recuperacion"),
]

SESSION_TYPE_LABELS = {
    "easy": "Suave",
    "base": "Base",
    "long": "Fondo",
    "tempo": "Tempo",
    "hard": "Fuerte",
    "intervals": "Intervalos",
    "technique": "Tecnica",
    "race": "Competencia",
    "recovery": "Recuperacion",
}

STEP_TYPE_OPTIONS = [
    Option("warmup", "Calentamiento"),
    Option("work", "Bloque"),
    Option("recovery", "Recuperacion"),
    Option("cooldown", "Vuelta a la calma"),
    Option("drills", "Tecnica"),
    Option("strides", "Strides"),
    Option("steady", "Continuo"),
    Option("swim_repeat", "Repeticion de natacion"),
    Option("transition", "Transicion"),
]

STEP_TYPE_LABELS = {
    "warmup": "Calentamiento",
    "work": "Bloque",
    "recovery": "Recuperacion",
    "cooldown": "Vuelta a la calma",
    "drills": "Tecnica",
    "strides": "Strides",
    "steady": "Continuo",
    "swim_repeat": "Repeticion de natacion",
    "transition": "Transicion",
}

GROUP_TYPE_OPTIONS = [
    Option("brick", "Brick"),
    Option("double_session", "Doble turno"),
    Option("complementary", "Complementario"),
    Option("pre_race", "Pre carrera"),
    Option("post_race", "Post carrera"),
    Option("technique", "Tecnica"),
    Option("custom", "Otro"),
]

GROUP_TYPE_LABELS = {
    "brick": "Brick",
    "double_session": "Doble turno",
    "multisport_block": "Bloque multideporte",
    "complementary": "Complementario",
    "pre_race": "Pre carrera",
    "post_race": "Post carrera",
    "technique": "Tecnica",
    "custom": "Otro",
}

DAY_TYPE_OPTIONS = [
    Option("easy", "Suave"),
    Option("quality", "Calidad"),
    Option("long", "Fondo"),
    Option("rest", "Descanso"),
    Option("race", "Competencia"),
]

DAY_TYPE_LABELS = {
    "easy": "Suave",
    "quality": "Calidad",
    "long": "Fondo",
    "rest": "Descanso",
    "race": "Competencia",
}

ZONE_OPTIONS = [
    Option("Z1", "Z1"),
    Option("Z2", "Z2"),
    Option("Z3", "Z3"),
    Option("Z4", "Z4"),
    Option("Z5", "Z5"),
]

MATCH_METHOD_LABELS = {
    "exact_time": "Horario exacto",
    "same_day_sport": "Mismo dia y deporte",
    "group_match": "Coincidencia por grupo",
    "manual": "Manual",
}

ANALYSIS_STATUS_LABELS = {
    "correct": "Correcto",
    "partial": "Parcial",
    "not_completed": "No completado",
    "review": "Revisar",
    "failed": "Fallido",
    "skipped": "Omitido",
}


def label_for(mapping: dict[str, str], value: str | None, fallback: str = "-") -> str:
    if not value:
        return fallback
    return mapping.get(value, mapping.get(value.lower(), value))
