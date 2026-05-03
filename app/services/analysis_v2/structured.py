from __future__ import annotations

from statistics import mean, pstdev
from typing import Any

from app.services.analysis_v2.scoring import average_scores, closeness_score_from_delta_pct, range_target_score, stability_score_from_cv


STRUCTURED_INTENT_INTERVALS = {"interval_training", "mixed_structured"}


def detect_session_intent(planned_session: Any, planned_steps: list[Any]) -> str:
    if not planned_steps:
        return _fallback_intent(planned_session)

    has_repeats = any(step.repeat_count and step.repeat_count > 1 for step in planned_steps)
    target_types = {step.target_type for step in planned_steps if step.target_type}
    target_zones = {(_target_zone(step) or "").lower() for step in planned_steps if _target_zone(step)}
    target_zones = {zone for zone in target_zones if zone}

    if has_repeats and len(target_types) > 1:
        return "mixed_structured"
    if has_repeats:
        return "interval_training"

    dominant_zone = _dominant_zone(target_zones)
    if dominant_zone in {"z1"}:
        return "recovery"
    if dominant_zone in {"z2"}:
        return "base_aerobic"
    if dominant_zone in {"z3"}:
        return "tempo"
    if dominant_zone in {"z4"}:
        return "threshold"
    if dominant_zone in {"z5"}:
        return "vo2max"

    return _fallback_intent(planned_session)


def expand_planned_steps(planned_steps: list[Any]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    repeat_group_id = 0
    index = 0
    while index < len(planned_steps):
        step = planned_steps[index]
        repeat_count = step.repeat_count or 1
        if repeat_count > 1:
            group_steps: list[Any] = []
            while index < len(planned_steps) and (planned_steps[index].repeat_count or 1) == repeat_count:
                group_steps.append(planned_steps[index])
                index += 1
            repeat_group_id += 1
            for iteration in range(1, repeat_count + 1):
                for group_step in group_steps:
                    expanded.append(_expanded_step(group_step, repeat_group_id, iteration, repeat_count))
        else:
            expanded.append(_expanded_step(step, None, None, None))
            index += 1
    return expanded


def build_expected_repeats_summary(planned_steps: list[Any]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    index = 0
    group_id = 0
    while index < len(planned_steps):
        step = planned_steps[index]
        repeat_count = step.repeat_count or 1
        if repeat_count > 1:
            group_steps: list[Any] = []
            while index < len(planned_steps) and (planned_steps[index].repeat_count or 1) == repeat_count:
                group_steps.append(planned_steps[index])
                index += 1
            group_id += 1
            summary.append(
                {
                    "repeat_group_id": group_id,
                    "repeat_count": repeat_count,
                    "step_count": len(group_steps),
                    "targets": [_target_label(item) for item in group_steps],
                }
            )
        else:
            index += 1
    return summary


def build_primary_targets(expanded_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    for step in expanded_steps:
        role = step["role"]
        target_type = step["target_type"]
        zone = step["target_zone"]
        key = (role, target_type, zone)
        if key not in buckets:
            buckets[key] = {
                "role": role,
                "target_type": target_type,
                "target_zone": zone,
                "repeat_count": 0,
            }
        buckets[key]["repeat_count"] += 1
    return list(buckets.values())


def build_block_structure(expanded_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    structure: list[dict[str, Any]] = []
    for step in expanded_steps:
        structure.append(
            {
                "role": step["role"],
                "target_type": step["target_type"],
                "target_zone": step["target_zone"],
                "duration_sec": step["duration_sec"],
                "distance_m": step["distance_m"],
                "repeat_group_id": step["repeat_group_id"],
                "repeat_iteration": step["repeat_iteration"],
            }
        )
    return structure


def match_steps_to_laps(expanded_steps: list[dict[str, Any]], laps: list[Any]) -> dict[str, Any]:
    structural_laps: list[tuple[int, Any]] = []
    unmatched_laps: list[int] = []
    for original_index, lap in enumerate(laps):
        if _is_non_structural_lap(lap):
            unmatched_laps.append(original_index)
        else:
            structural_laps.append((original_index, lap))

    unmatched_steps: list[int] = []
    if not expanded_steps and not structural_laps:
        return {
            "matched_pairs": [],
            "unmatched_laps": unmatched_laps,
            "unmatched_steps": unmatched_steps,
            "matched_count": 0,
            "alignment_score": None,
            "interval_structure_detected": False,
            "structural_confidence": None,
        }

    if _should_use_direct_sequential_match(expanded_steps, structural_laps):
        matched_pairs, direct_unmatched_steps, direct_unmatched_laps, total_cost = _direct_sequential_match(expanded_steps, structural_laps)
    else:
        matched_pairs, direct_unmatched_steps, direct_unmatched_laps, total_cost = _dynamic_sequential_match(expanded_steps, structural_laps)

    unmatched_steps.extend(direct_unmatched_steps)
    unmatched_laps.extend(direct_unmatched_laps)
    unmatched_laps.sort()
    unmatched_steps.sort()

    matched_count = len(matched_pairs)
    interval_structure_detected = any(step["repeat_group_id"] is not None for step in expanded_steps)
    coverage_steps = matched_count / max(len(expanded_steps), 1)
    coverage_laps = matched_count / max(len(structural_laps), 1) if structural_laps else 1.0
    coverage_score = round(min(coverage_steps, coverage_laps) * 100.0, 1)
    average_cost = (total_cost / matched_count) if matched_count else 100.0
    quality_score = max(0.0, 100.0 - average_cost)
    alignment_score = round((coverage_score * 0.7) + (quality_score * 0.3), 1)
    structural_confidence = round((coverage_steps * 60.0) + (quality_score * 0.4), 1) if expanded_steps else None

    return {
        "matched_pairs": matched_pairs,
        "unmatched_laps": unmatched_laps,
        "unmatched_steps": unmatched_steps,
        "matched_count": matched_count,
        "alignment_score": alignment_score,
        "interval_structure_detected": interval_structure_detected,
        "structural_confidence": structural_confidence,
    }


def _should_use_direct_sequential_match(
    expanded_steps: list[dict[str, Any]],
    structural_laps: list[tuple[int, Any]],
) -> bool:
    if not expanded_steps or not structural_laps:
        return False
    if abs(len(expanded_steps) - len(structural_laps)) > 0:
        return False

    acceptable = 0
    total = min(len(expanded_steps), len(structural_laps))
    for lap_position, (step, (_, lap)) in enumerate(zip(expanded_steps, structural_laps)):
        debug = _match_debug_for_pair(step, lap, structural_laps, lap_position)
        if debug["duration_ratio"] is None or debug["duration_ratio"] <= 0.4:
            acceptable += 1
    return total > 0 and acceptable / total >= 0.8


def _direct_sequential_match(
    expanded_steps: list[dict[str, Any]],
    structural_laps: list[tuple[int, Any]],
) -> tuple[list[dict[str, Any]], list[int], list[int], float]:
    matched_pairs: list[dict[str, Any]] = []
    total_cost = 0.0
    common = min(len(expanded_steps), len(structural_laps))
    for step_index in range(common):
        original_lap_index, lap = structural_laps[step_index]
        debug = _match_debug_for_pair(expanded_steps[step_index], lap, structural_laps, step_index)
        total_cost += debug["total_penalty"]
        matched_pairs.append(
            {
                "step_index": step_index,
                "lap_index": original_lap_index,
                "step": expanded_steps[step_index],
                "lap_summary": _lap_summary(lap),
                **debug,
            }
        )

    unmatched_steps = list(range(common, len(expanded_steps)))
    unmatched_laps = [original_index for original_index, _ in structural_laps[common:]]
    return matched_pairs, unmatched_steps, unmatched_laps, total_cost


def _dynamic_sequential_match(
    expanded_steps: list[dict[str, Any]],
    structural_laps: list[tuple[int, Any]],
) -> tuple[list[dict[str, Any]], list[int], list[int], float]:
    step_count = len(expanded_steps)
    lap_count = len(structural_laps)
    skip_step_penalty = 55.0
    skip_lap_penalty = 48.0
    inf = 10**9

    dp = [[float(inf)] * (lap_count + 1) for _ in range(step_count + 1)]
    back: list[list[tuple[str, Any] | None]] = [[None] * (lap_count + 1) for _ in range(step_count + 1)]
    dp[0][0] = 0.0

    for step_index in range(step_count + 1):
        for lap_index in range(lap_count + 1):
            current = dp[step_index][lap_index]
            if current >= inf:
                continue
            if step_index < step_count and lap_index < lap_count:
                _, lap = structural_laps[lap_index]
                debug = _match_debug_for_pair(expanded_steps[step_index], lap, structural_laps, lap_index)
                candidate_cost = current + debug["total_penalty"]
                if candidate_cost < dp[step_index + 1][lap_index + 1]:
                    dp[step_index + 1][lap_index + 1] = candidate_cost
                    back[step_index + 1][lap_index + 1] = ("match", debug)
            if step_index < step_count:
                candidate_cost = current + skip_step_penalty
                if candidate_cost < dp[step_index + 1][lap_index]:
                    dp[step_index + 1][lap_index] = candidate_cost
                    back[step_index + 1][lap_index] = ("skip_step", None)
            if lap_index < lap_count:
                candidate_cost = current + skip_lap_penalty
                if candidate_cost < dp[step_index][lap_index + 1]:
                    dp[step_index][lap_index + 1] = candidate_cost
                    back[step_index][lap_index + 1] = ("skip_lap", None)

    step_index = step_count
    lap_index = lap_count
    matched_pairs_rev: list[dict[str, Any]] = []
    unmatched_steps: list[int] = []
    unmatched_laps: list[int] = []

    while step_index > 0 or lap_index > 0:
        move = back[step_index][lap_index]
        if move is None:
            if step_index > 0:
                step_index -= 1
                unmatched_steps.append(step_index)
            elif lap_index > 0:
                lap_index -= 1
                unmatched_laps.append(structural_laps[lap_index][0])
            continue

        kind, payload = move
        if kind == "match":
            step_index -= 1
            lap_index -= 1
            original_lap_index, lap = structural_laps[lap_index]
            matched_pairs_rev.append(
                {
                    "step_index": step_index,
                    "lap_index": original_lap_index,
                    "step": expanded_steps[step_index],
                    "lap_summary": _lap_summary(lap),
                    **payload,
                }
            )
        elif kind == "skip_step":
            step_index -= 1
            unmatched_steps.append(step_index)
        else:
            lap_index -= 1
            unmatched_laps.append(structural_laps[lap_index][0])

    matched_pairs_rev.reverse()
    unmatched_steps.reverse()
    unmatched_laps.reverse()
    return matched_pairs_rev, unmatched_steps, unmatched_laps, dp[step_count][lap_count]


def _match_debug_for_pair(
    step: dict[str, Any],
    lap: Any,
    structural_laps: list[tuple[int, Any]],
    lap_position: int,
) -> dict[str, Any]:
    duration_penalty, duration_ratio = _duration_penalty(step, lap)
    role_penalty, role_reason = _role_penalty(step, lap, structural_laps, lap_position)
    intensity_penalty, intensity_reason = _intensity_penalty(step, lap)
    jump_penalty = 0.0
    total_penalty = round(duration_penalty + role_penalty + intensity_penalty + jump_penalty, 1)
    chosen_match_reason = _chosen_match_reason(step, lap, duration_ratio, role_reason, intensity_reason)
    rejected_candidates = _rejected_candidates(step, structural_laps, lap_position)
    return {
        "duration_penalty": duration_penalty,
        "duration_ratio": duration_ratio,
        "role_penalty": role_penalty,
        "intensity_penalty": intensity_penalty,
        "jump_penalty": jump_penalty,
        "chosen_match_reason": chosen_match_reason,
        "rejected_candidates": rejected_candidates,
        "total_penalty": total_penalty,
    }


def _duration_penalty(step: dict[str, Any], lap: Any) -> tuple[float, float | None]:
    step_duration = step.get("duration_sec")
    lap_duration = _lap_duration_seconds(lap)
    if step_duration and lap_duration:
        ratio = abs(lap_duration - step_duration) / max(step_duration, 1)
        if ratio <= 0.1:
            penalty = ratio * 20.0
        elif ratio <= 0.25:
            penalty = 4.0 + ((ratio - 0.1) * 40.0)
        elif ratio <= 0.4:
            penalty = 12.0 + ((ratio - 0.25) * 80.0)
        elif ratio <= 0.75:
            penalty = 30.0 + ((ratio - 0.4) * 120.0)
        else:
            penalty = 72.0 + ((ratio - 0.75) * 80.0)
        return round(penalty, 1), round(ratio, 3)

    step_distance = step.get("distance_m")
    lap_distance = _lap_distance_meters(lap)
    if step_distance and lap_distance:
        ratio = abs(lap_distance - step_distance) / max(step_distance, 1)
        if ratio <= 0.1:
            penalty = ratio * 20.0
        elif ratio <= 0.25:
            penalty = 4.0 + ((ratio - 0.1) * 40.0)
        elif ratio <= 0.4:
            penalty = 12.0 + ((ratio - 0.25) * 80.0)
        elif ratio <= 0.75:
            penalty = 30.0 + ((ratio - 0.4) * 120.0)
        else:
            penalty = 72.0 + ((ratio - 0.75) * 80.0)
        return round(penalty, 1), round(ratio, 3)

    return 28.0, None


def _role_penalty(
    step: dict[str, Any],
    lap: Any,
    structural_laps: list[tuple[int, Any]],
    lap_position: int,
) -> tuple[float, str | None]:
    role = step.get("role")
    step_duration = step.get("duration_sec")
    lap_duration = _lap_duration_seconds(lap)
    penalty = 0.0
    reason: str | None = None

    if role == "work" and step_duration and lap_duration and lap_duration > step_duration * 1.75:
        penalty += 28.0
        reason = "lap demasiado largo para bloque de trabajo"
    elif role == "work" and step_duration and lap_duration and lap_duration > step_duration * 1.4:
        penalty += 14.0
        reason = "lap algo largo para bloque de trabajo"

    if role in {"recovery", "cooldown"} and step_duration and lap_duration and lap_duration < step_duration * 0.45:
        penalty += 18.0
        reason = "lap demasiado corto para bloque suave"

    if role == "cooldown" and lap_position == len(structural_laps) - 1:
        cooldown_bonus = _cooldown_end_bonus(lap, structural_laps, lap_position)
        penalty -= cooldown_bonus
        if cooldown_bonus > 0 and reason is None:
            reason = "ultimo lap favorecido como cooldown final"

    return round(max(0.0, penalty), 1), reason


def _intensity_penalty(step: dict[str, Any], lap: Any) -> tuple[float, str | None]:
    target_type = step.get("target_type")
    target_min = step.get("target_min")
    target_max = step.get("target_max")
    actual_value = _lap_value_for_target(lap, target_type)
    if target_type is None or actual_value is None or (target_min is None and target_max is None):
        return 0.0, None

    evaluation = range_target_score(actual_value, target_min, target_max, _target_margin(target_type))
    penalty = round((100.0 - evaluation["score"]) * 0.28, 1)
    reason = None
    if evaluation["status"] == "above_range":
        reason = "intensidad real por encima del objetivo"
    elif evaluation["status"] == "below_range":
        reason = "intensidad real por debajo del objetivo"
    return penalty, reason


def _cooldown_end_bonus(lap: Any, structural_laps: list[tuple[int, Any]], lap_position: int) -> float:
    if lap_position <= 0:
        return 0.0
    _, previous_lap = structural_laps[lap_position - 1]
    current_hr = _lap_value_for_target(lap, "hr")
    previous_hr = _lap_value_for_target(previous_lap, "hr")
    current_pace = _lap_value_for_target(lap, "pace")
    previous_pace = _lap_value_for_target(previous_lap, "pace")

    bonus = 0.0
    if current_hr is not None and previous_hr is not None and current_hr <= previous_hr:
        bonus += 5.0
    if current_pace is not None and previous_pace is not None and current_pace >= previous_pace:
        bonus += 5.0
    return bonus


def _chosen_match_reason(
    step: dict[str, Any],
    lap: Any,
    duration_ratio: float | None,
    role_reason: str | None,
    intensity_reason: str | None,
) -> str:
    reasons: list[str] = []
    if duration_ratio is not None and duration_ratio <= 0.15:
        reasons.append("duracion muy cercana")
    elif duration_ratio is not None and duration_ratio <= 0.4:
        reasons.append("duracion razonablemente alineada")
    elif duration_ratio is not None:
        reasons.append("duracion aceptada por falta de mejor opcion secuencial")
    if role_reason:
        reasons.append(f"rol: {role_reason}")
    if intensity_reason:
        reasons.append(intensity_reason)
    if not reasons:
        reasons.append("mejor opcion secuencial disponible")
    return "; ".join(reasons)


def _rejected_candidates(
    step: dict[str, Any],
    structural_laps: list[tuple[int, Any]],
    lap_position: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for candidate_position in range(lap_position + 1, min(len(structural_laps), lap_position + 3)):
        original_index, lap = structural_laps[candidate_position]
        duration_penalty, duration_ratio = _duration_penalty(step, lap)
        role_penalty, role_reason = _role_penalty(step, lap, structural_laps, candidate_position)
        intensity_penalty, intensity_reason = _intensity_penalty(step, lap)
        candidates.append(
            {
                "lap_index": original_index,
                "duration_ratio": duration_ratio,
                "duration_penalty": duration_penalty,
                "role_penalty": role_penalty,
                "intensity_penalty": intensity_penalty,
                "reason": "; ".join(part for part in (role_reason, intensity_reason) if part) or "peor costo secuencial",
            }
        )
    return candidates


def _lap_duration_seconds(lap: Any) -> int | None:
    if lap is None:
        return None
    if isinstance(lap, dict):
        return lap.get("duration_sec")
    return getattr(lap, "duration_sec", None)


def _lap_distance_meters(lap: Any) -> float | None:
    if lap is None:
        return None
    if isinstance(lap, dict):
        return lap.get("distance_m")
    return getattr(lap, "distance_m", None)


def build_block_analysis(match_result: dict[str, Any]) -> list[dict[str, Any]]:
    analysis: list[dict[str, Any]] = []
    for pairing in match_result.get("matched_pairs", []):
        step = pairing["step"]
        lap = pairing["lap_summary"]
        target_type = step["target_type"]
        target_min = step.get("target_min")
        target_max = step.get("target_max")
        actual_value = _lap_value_for_target(lap, target_type)
        evaluation = None
        if target_type and actual_value is not None and (target_min is not None or target_max is not None):
            evaluation = range_target_score(actual_value, target_min, target_max, _target_margin(target_type))
        within_range = evaluation["within_range"] if evaluation else None
        score = evaluation["score"] if evaluation else None
        duration_delta_pct = _delta_pct(step.get("duration_sec"), lap.get("duration_sec"))
        distance_delta_pct = _delta_pct(step.get("distance_m"), lap.get("distance_m"))
        consistency_score = _consistency_score(duration_delta_pct, distance_delta_pct)

        analysis.append(
            {
                "planned_label": _step_label(step),
                "role": step["role"],
                "target_type": target_type,
                "target_zone": step["target_zone"],
                "target_source": step.get("target_source"),
                "planned_target_min": target_min,
                "planned_target_max": target_max,
                "target_range": {"min": target_min, "max": target_max} if target_min is not None or target_max is not None else None,
                "planned_duration_sec": step.get("duration_sec"),
                "planned_distance_m": step.get("distance_m"),
                "actual_duration_sec": lap.get("duration_sec"),
                "actual_distance_m": lap.get("distance_m"),
                "duration_delta_pct": duration_delta_pct,
                "distance_delta_pct": distance_delta_pct,
                "consistency_score": consistency_score,
                "actual_value": actual_value,
                "activity_lap_index": lap.get("index"),
                "within_range": within_range,
                "score": score,
                "short_note": _block_short_note(within_range, target_type),
            }
        )
    return analysis


def apply_block_short_notes(block_analysis: list[dict[str, Any]], recovery_block_not_effective_flag: bool) -> list[dict[str, Any]]:
    for block in block_analysis:
        block["short_note"] = _short_note_for_block(block, recovery_block_not_effective_flag)
    return block_analysis


def compute_execution_score_structured(match_result: dict[str, Any], block_analysis: list[dict[str, Any]]) -> dict[str, Any]:
    work_scores: list[float] = []
    recovery_scores: list[float] = []

    for block in block_analysis:
        target_score = block.get("score")
        consistency_score = block.get("consistency_score")
        if target_score is None and consistency_score is None:
            continue
        if target_score is None:
            block_score = consistency_score
        elif consistency_score is None:
            block_score = target_score
        else:
            block_score = round((target_score * 0.7) + (consistency_score * 0.3), 1)
        if block_score is None:
            continue
        if block.get("role") == "recovery":
            recovery_scores.append(block_score)
        else:
            work_scores.append(block_score)

    work_score = average_scores(work_scores) if work_scores else None
    recovery_score = average_scores(recovery_scores) if recovery_scores else None
    execution_score = _weighted_average(work_score, recovery_score, 0.6, 0.4)

    return {
        "execution_score": execution_score,
        "role_scores": {
            "work": work_score,
            "recovery": recovery_score,
        },
        "block_score_formula": "block_score = target_compliance*0.7 + consistency*0.3",
    }


def derive_structured_flags(session_intent: str, match_result: dict[str, Any], block_analysis: list[dict[str, Any]]) -> dict[str, Any]:
    expected_variability = session_intent in STRUCTURED_INTENT_INTERVALS
    work_blocks = [block for block in block_analysis if block["role"] == "work"]
    recovery_blocks = [block for block in block_analysis if block["role"] == "recovery"]

    work_under = _count_target_status(work_blocks, "below_range")
    work_over = _count_target_status(work_blocks, "above_range")
    recovery_fast = _count_target_status(recovery_blocks, "above_range")

    work_block_inconsistency_flag = False
    if work_blocks:
        scores = [block["score"] for block in work_blocks if block["score"] is not None]
        if scores and pstdev(scores) >= 12:
            work_block_inconsistency_flag = True

    recovery_block_not_effective_flag = False
    if recovery_blocks:
        out_of_range = sum(1 for block in recovery_blocks if block.get("within_range") is False)
        recovery_block_not_effective_flag = out_of_range >= max(1, len(recovery_blocks) // 2)

    return {
        "expected_variability": expected_variability,
        "work_block_inconsistency_flag": work_block_inconsistency_flag,
        "recovery_block_too_fast_flag": recovery_fast >= max(1, len(recovery_blocks) // 2) if recovery_blocks else False,
        "recovery_block_not_effective_flag": recovery_block_not_effective_flag,
        "work_block_under_target_flag": work_under >= max(1, len(work_blocks) // 2) if work_blocks else False,
        "work_block_over_target_flag": work_over >= max(1, len(work_blocks) // 2) if work_blocks else False,
        "interval_structure_low_confidence_flag": bool(match_result.get("structural_confidence") is not None and match_result["structural_confidence"] < 55),
    }


def _expanded_step(step: Any, repeat_group_id: int | None, repeat_iteration: int | None, repeat_count: int | None) -> dict[str, Any]:
    target_zone = _target_zone(step)
    explicit_target = bool(step.target_type or target_zone or step.target_hr_min or step.target_hr_max or step.target_pace_min_sec_km or step.target_pace_max_sec_km or step.target_power_min or step.target_power_max)
    return {
        "order": step.order,
        "repeat_group_id": repeat_group_id,
        "repeat_iteration": repeat_iteration,
        "repeat_count": repeat_count,
        "step_type": step.step_type,
        "duration_sec": step.duration_sec,
        "distance_m": step.distance_m,
        "target_type": step.target_type,
        "target_zone": target_zone,
        "target_hr_min": step.target_hr_min,
        "target_hr_max": step.target_hr_max,
        "target_power_min": step.target_power_min,
        "target_power_max": step.target_power_max,
        "target_pace_min_sec_km": step.target_pace_min_sec_km,
        "target_pace_max_sec_km": step.target_pace_max_sec_km,
        "target_notes": step.target_notes,
        "target_min": _target_min(step),
        "target_max": _target_max(step),
        "target_source": "explicit" if explicit_target else None,
        "role": _infer_role(step.step_type, target_zone),
    }


def _infer_role(step_type: str | None, target_zone: str | None) -> str:
    normalized_step = (step_type or "").lower()
    if normalized_step in {"warmup", "cooldown"}:
        return normalized_step
    if target_zone and target_zone.lower() in {"z1", "z2"}:
        return "recovery"
    return "work"


def _target_zone(step: Any) -> str | None:
    return step.target_hr_zone or step.target_pace_zone or step.target_power_zone or step.target_rpe_zone


def _target_label(step: Any) -> str:
    zone = _target_zone(step)
    if zone:
        return f"{step.target_type or 'intensity'} {zone}"
    return step.target_type or "sin_target"


def _target_min(step: Any) -> float | int | None:
    if step.target_type == "hr":
        return step.target_hr_min
    if step.target_type == "pace":
        return step.target_pace_min_sec_km
    if step.target_type == "power":
        return step.target_power_min
    if step.target_type == "rpe":
        return None
    return None


def _target_max(step: Any) -> float | int | None:
    if step.target_type == "hr":
        return step.target_hr_max
    if step.target_type == "pace":
        return step.target_pace_max_sec_km
    if step.target_type == "power":
        return step.target_power_max
    if step.target_type == "rpe":
        return None
    return None


def _lap_value_for_target(lap: Any, target_type: str | None) -> float | int | None:
    if target_type == "hr":
        return lap.get("avg_hr") if isinstance(lap, dict) else lap.avg_hr
    if target_type == "pace":
        return lap.get("avg_pace_sec_km") if isinstance(lap, dict) else lap.avg_pace_sec_km
    if target_type == "power":
        return lap.get("avg_power") if isinstance(lap, dict) else lap.avg_power
    if target_type == "rpe":
        return None
    return None


def _target_margin(target_type: str | None) -> float:
    if target_type == "hr":
        return 5.0
    if target_type == "pace":
        return 8.0
    if target_type == "power":
        return 15.0
    return 0.0


def _block_short_note(within_range: bool | None, target_type: str | None) -> str | None:
    if within_range is None:
        return None
    if within_range:
        return "dentro de rango"
    if target_type in {"pace", "power"}:
        return "fuera de rango"
    if target_type == "hr":
        return "fuera de rango"
    return None


def _short_note_for_block(block: dict[str, Any], recovery_block_not_effective_flag: bool) -> str | None:
    role = block.get("role")
    target_type = block.get("target_type")
    within_range = block.get("within_range")
    if within_range is None or target_type is None:
        return block.get("short_note")

    direction, delta_value = _target_delta_direction(
        block.get("actual_value"),
        block.get("planned_target_min"),
        block.get("planned_target_max"),
    )

    if role == "recovery" and target_type == "hr":
        if within_range:
            return "recuperacion efectiva"
        if recovery_block_not_effective_flag and direction == "above":
            return "recuperacion insuficiente para volver a Z2"
        if direction == "above":
            if _is_slight_delta(target_type, delta_value):
                return "recuperacion algo alta"
            return "recuperacion demasiado alta"
        if direction == "below":
            return "intensidad insuficiente"
        return "recuperacion fuera de rango"

    if role == "work":
        if within_range:
            return "trabajo dentro de rango"
        if direction == "above":
            if _is_slight_delta(target_type, delta_value):
                return "trabajo ligeramente exigente"
            return "trabajo demasiado exigente"
        if direction == "below":
            if target_type == "pace" and _is_slight_delta(target_type, delta_value):
                return "trabajo ligeramente por debajo"
            if target_type == "hr":
                return "intensidad insuficiente"
            return "trabajo por debajo del objetivo"
        return "trabajo fuera de rango"

    if within_range:
        return "dentro de rango"
    return "fuera de rango"


def _target_delta_direction(actual: float | int | None, min_value: float | int | None, max_value: float | int | None) -> tuple[str | None, float | None]:
    if actual is None or (min_value is None and max_value is None):
        return None, None
    if max_value is not None and actual > max_value:
        return "below", float(actual - max_value)
    if min_value is not None and actual < min_value:
        return "above", float(min_value - actual)
    return "within", 0.0


def _is_slight_delta(target_type: str | None, delta_value: float | None) -> bool:
    if delta_value is None:
        return False
    if target_type == "hr":
        return delta_value <= 5.0
    if target_type == "pace":
        return delta_value <= 8.0
    if target_type == "power":
        return delta_value <= 15.0
    return delta_value <= 5.0


def _step_label(step: dict[str, Any]) -> str:
    if step.get("distance_m"):
        measurement = _format_distance(step["distance_m"])
    elif step.get("duration_sec"):
        measurement = _format_duration(step["duration_sec"])
    else:
        measurement = "bloque"

    target_type = _target_type_label(step.get("target_type"))
    zone = _zone_label(step.get("target_zone"))
    parts = [measurement]
    if target_type:
        parts.append(target_type)
    if zone:
        parts.append(zone)
    return " ".join(parts)


def _format_duration(seconds: int) -> str:
    if seconds < 120:
        return f"{int(round(seconds))}s"
    minutes = int(round(seconds / 60.0))
    if minutes < 60:
        return f"{minutes}min"
    hours = minutes // 60
    rem = minutes % 60
    return f"{hours}h{str(rem).zfill(2)}"


def _format_distance(meters: float) -> str:
    km = meters / 1000.0
    if km >= 1:
        trimmed = f"{round(km, 2)}".rstrip("0").rstrip(".")
        return f"{trimmed}km"
    return f"{round(meters)}m"


def _lap_summary(lap: Any) -> dict[str, Any]:
    return {
        "index": getattr(lap, "index", None),
        "duration_sec": getattr(lap, "duration_sec", None),
        "distance_m": getattr(lap, "distance_m", None),
        "avg_hr": getattr(lap, "avg_hr", None),
        "avg_pace_sec_km": getattr(lap, "avg_pace_sec_km", None),
        "avg_power": getattr(lap, "avg_power", None),
        "avg_cadence": getattr(lap, "avg_cadence", None),
        "lap_type": getattr(lap, "lap_type", None),
    }


def _consistency_score(duration_delta_pct: float | None, distance_delta_pct: float | None) -> float | None:
    scores: list[float | None] = []
    if duration_delta_pct is not None:
        scores.append(closeness_score_from_delta_pct(duration_delta_pct))
    if distance_delta_pct is not None:
        scores.append(closeness_score_from_delta_pct(distance_delta_pct))
    return average_scores(scores)


def _weighted_average(work_score: float | None, recovery_score: float | None, work_weight: float, recovery_weight: float) -> float | None:
    total_weight = 0.0
    total_value = 0.0
    if work_score is not None:
        total_weight += work_weight
        total_value += work_score * work_weight
    if recovery_score is not None:
        total_weight += recovery_weight
        total_value += recovery_score * recovery_weight
    if total_weight == 0:
        return None
    return round(total_value / total_weight, 1)


def _target_type_label(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized == "hr":
        return "HR"
    if normalized == "pace":
        return "pace"
    if normalized == "power":
        return "power"
    if normalized == "rpe":
        return "rpe"
    return value


def _zone_label(zone: str | None) -> str | None:
    if not zone:
        return None
    normalized = zone.strip().upper()
    if not normalized.startswith("Z"):
        normalized = f"Z{normalized}"
    return normalized


def _delta_pct(reference: float | int | None, actual: float | int | None) -> float | None:
    if reference is None or actual is None or float(reference) == 0:
        return None
    return round(((float(actual) - float(reference)) / float(reference)) * 100.0, 1)


def _count_target_status(blocks: list[dict[str, Any]], status: str) -> int:
    count = 0
    for block in blocks:
        if block.get("score") is None:
            continue
        evaluation_status = "within_range" if block.get("within_range") else "below_range"
        if block.get("within_range") is None:
            continue
        if not block.get("within_range"):
            evaluation_status = "below_range"
        if status == "above_range" and block.get("within_range") is False:
            if block.get("actual_value") is not None and block.get("planned_target_max") is not None:
                if block["actual_value"] > block["planned_target_max"]:
                    count += 1
            continue
        if status == "below_range" and block.get("within_range") is False:
            if block.get("actual_value") is not None and block.get("planned_target_min") is not None:
                if block["actual_value"] < block["planned_target_min"]:
                    count += 1
            continue
        if status == evaluation_status:
            count += 1
    return count


def _is_non_structural_lap(lap: Any) -> bool:
    if lap is None:
        return True
    label = (lap.lap_type or "").lower()
    if any(marker in label for marker in ("pause", "rest", "idle", "manual")):
        return True
    duration = lap.duration_sec or 0
    distance = lap.distance_m or 0.0
    return duration < 20 and distance < 50


def _dominant_zone(zones: set[str]) -> str | None:
    if not zones:
        return None
    ordered = ["z1", "z2", "z3", "z4", "z5"]
    for zone in ordered:
        if zone in zones:
            return zone
    return None


def _fallback_intent(planned_session: Any) -> str:
    if planned_session.session_type:
        return str(planned_session.session_type)
    if planned_session.target_type:
        return f"{planned_session.target_type}_focus"
    return "indeterminada"


def _coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean_value = mean(values)
    if mean_value == 0:
        return None
    return round(pstdev(values) / mean_value, 4)
