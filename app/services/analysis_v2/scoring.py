from __future__ import annotations

from typing import Iterable


def clamp_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(100.0, value)), 1)


def average_scores(values: Iterable[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 1)


def closeness_score_from_delta_pct(delta_pct: float | None) -> float | None:
    if delta_pct is None:
        return None
    return clamp_score(100.0 - abs(delta_pct))


def stability_score_from_cv(cv_ratio: float | None) -> float | None:
    if cv_ratio is None:
        return None
    # 0.00 = 100; 0.05 = 80; 0.10 = 60
    return clamp_score(100.0 - (cv_ratio * 400.0))


def range_target_score(
    value: float | None,
    minimum: float | None,
    maximum: float | None,
    soft_margin: float,
    *,
    higher_is_better: bool = False,
) -> dict[str, float | str | bool | None]:
    if value is None or (minimum is None and maximum is None):
        return {
            "score": None,
            "status": "not_evaluable",
            "within_range": None,
            "delta_to_range": None,
        }

    if minimum is not None and value < minimum:
        delta = minimum - value
        if delta <= soft_margin:
            score = 85.0
        else:
            score = max(0.0, 85.0 - ((delta - soft_margin) / max(soft_margin, 1)) * 20.0)
        status = "above_range" if higher_is_better else "below_range"
        return {
            "score": clamp_score(score),
            "status": status,
            "within_range": False,
            "delta_to_range": round(delta, 2),
        }

    if maximum is not None and value > maximum:
        delta = value - maximum
        if delta <= soft_margin:
            score = 85.0
        else:
            score = max(0.0, 85.0 - ((delta - soft_margin) / max(soft_margin, 1)) * 20.0)
        status = "below_range" if higher_is_better else "above_range"
        return {
            "score": clamp_score(score),
            "status": status,
            "within_range": False,
            "delta_to_range": round(delta, 2),
        }

    return {
        "score": 100.0,
        "status": "within_range",
        "within_range": True,
        "delta_to_range": 0.0,
    }
