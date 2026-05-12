from __future__ import annotations

from app.ui.catalogs import MODALITY_LABELS


SUPPORTED_MODALITIES = {"outdoor", "indoor", "virtual", "unknown"}


def normalize_modality(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    return normalized.replace("-", "_").replace(" ", "_")


def validate_modality(value: str | None) -> str | None:
    normalized = normalize_modality(value)
    if normalized is None:
        return None
    if normalized not in SUPPORTED_MODALITIES:
        raise ValueError(f"Unsupported modality: {value}")
    return normalized


def modality_label(value: str | None, fallback: str = "-") -> str:
    normalized = normalize_modality(value)
    if normalized is None:
        return fallback
    return MODALITY_LABELS.get(normalized, normalized.replace("_", " ").title())


def preferred_modality(*values: str | None) -> str | None:
    for value in values:
        normalized = normalize_modality(value)
        if normalized and normalized != "unknown":
            return normalized
    for value in values:
        normalized = normalize_modality(value)
        if normalized:
            return normalized
    return None


def garmin_modality(raw_sport_type: str | None) -> str | None:
    normalized = normalize_modality(raw_sport_type)
    if normalized in {"indoor_cycling", "treadmill_running", "indoor_cardio"}:
        return "indoor"
    if normalized in {"virtual_ride", "virtual_cycling"}:
        return "virtual"
    return None


def garmin_canonical_sport_type(raw_sport_type: str | None) -> str | None:
    normalized = normalize_modality(raw_sport_type)
    mapping = {
        "indoor_cycling": "cycling",
        "treadmill_running": "running",
        "virtual_ride": "cycling",
        "virtual_cycling": "cycling",
        "indoor_cardio": "other",
    }
    if normalized in mapping:
        return mapping[normalized]
    return raw_sport_type
