from __future__ import annotations

from typing import Iterable


def compare_relative(expected: float | None, actual: float | None) -> dict[str, float | str | None]:
    if expected in (None, 0) or actual is None:
        return {"score": None, "status": "review", "delta_pct": None, "fulfillment_pct": None}

    delta_pct = abs(actual - expected) / expected * 100.0
    fulfillment_pct = min((actual / expected) * 100.0, 999.0) if expected else None
    if delta_pct <= 10:
        score = 100.0
        status = "correct"
    elif delta_pct <= 20:
        score = 70.0
        status = "partial"
    else:
        score = 35.0
        status = "failed"
    return {
        "score": score,
        "status": status,
        "delta_pct": round(delta_pct, 1),
        "fulfillment_pct": round(fulfillment_pct, 1) if fulfillment_pct is not None else None,
    }


def compare_range(
    minimum: float | None,
    maximum: float | None,
    actual: float | None,
    *,
    partial_tolerance: float | None = None,
) -> dict[str, float | str | None]:
    if actual is None or (minimum is None and maximum is None):
        return {"score": None, "status": "review", "distance": None, "direction": None}

    lower = minimum if minimum is not None else maximum
    upper = maximum if maximum is not None else minimum
    assert lower is not None and upper is not None
    if lower > upper:
        lower, upper = upper, lower

    if lower <= actual <= upper:
        return {"score": 100.0, "status": "correct", "distance": 0.0, "direction": "within"}

    tolerance = partial_tolerance if partial_tolerance is not None else max((upper - lower) * 0.15, 5.0)
    if actual < lower:
        distance = lower - actual
        direction = "below"
    else:
        distance = actual - upper
        direction = "above"

    if distance <= tolerance:
        return {"score": 70.0, "status": "partial", "distance": round(distance, 1), "direction": direction}
    return {"score": 35.0, "status": "failed", "distance": round(distance, 1), "direction": direction}


def aggregate_scores(global_scores: Iterable[float | None], item_scores: Iterable[float | None]) -> float | None:
    usable_global = [score for score in global_scores if score is not None]
    usable_items = [score for score in item_scores if score is not None]

    if usable_global and usable_items:
        return round((sum(usable_global) / len(usable_global)) * 0.6 + (sum(usable_items) / len(usable_items)) * 0.4, 1)
    if usable_global:
        return round(sum(usable_global) / len(usable_global), 1)
    if usable_items:
        return round(sum(usable_items) / len(usable_items), 1)
    return None


def overall_status_from_score(score: float | None, *, force_review: bool = False) -> str:
    if force_review or score is None:
        return "review"
    if score >= 85:
        return "correct"
    if score >= 60:
        return "partial"
    return "not_completed"


def item_status_from_score(score: float | None, *, skipped: bool = False, force_review: bool = False) -> str:
    if skipped:
        return "skipped"
    if force_review or score is None:
        return "review"
    if score >= 85:
        return "correct"
    if score >= 60:
        return "partial"
    return "failed"
