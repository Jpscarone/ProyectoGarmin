from __future__ import annotations

from statistics import mean, pstdev
from typing import Any

from app.services.analysis_v2 import rules
from app.services.analysis_v2.scoring import average_scores, closeness_score_from_delta_pct, range_target_score, stability_score_from_cv
from app.services.analysis_v2.structured import (
    apply_block_short_notes,
    build_block_analysis,
    build_block_structure,
    build_expected_repeats_summary,
    build_primary_targets,
    compute_execution_score_structured,
    detect_session_intent,
    derive_structured_flags,
    expand_planned_steps,
    match_steps_to_laps,
)


def compute_session_metrics(context: Any) -> dict[str, Any]:
    structured_plan = _build_structured_plan(context)
    planned_vs_actual = _build_planned_vs_actual(context)
    elevation = _build_elevation_metrics(context, planned_vs_actual)
    heart_rate = _build_heart_rate_metrics(context)
    pace = _build_pace_metrics(context)
    power = _build_power_metrics(context)
    cadence = _build_cadence_metrics(context)
    laps = _build_lap_metrics(context, structured_plan)
    block_analysis = build_block_analysis(laps.get("structured_match", {})) if laps.get("structured_match") else []
    intensity = _build_intensity_metrics(context, structured_plan)
    recent_comparisons = _build_recent_similar_comparisons(context)
    weekly_context = _build_weekly_context(context)
    compliance = _build_compliance_metrics(planned_vs_actual, laps)
    derived_flags = _build_flags(context, planned_vs_actual, heart_rate, pace, intensity, laps, structured_plan, block_analysis)
    block_analysis = apply_block_short_notes(block_analysis, derived_flags.get("recovery_block_not_effective_flag", False))
    scores = _build_scores(context, compliance, heart_rate, pace, power, cadence, intensity, laps, structured_plan, block_analysis)

    return {
        "session_intent": structured_plan["session_intent"],
        "planned_vs_actual": planned_vs_actual,
        "intensity": intensity,
        "heart_rate": heart_rate,
        "pace": pace,
        "power": power,
        "cadence": cadence,
        "elevation": elevation,
        "laps": laps,
        "block_analysis": block_analysis,
        "structure": {
            "session_intent": structured_plan["session_intent"],
            "primary_targets": structured_plan["primary_targets"],
            "block_structure": structured_plan["block_structure"],
            "expected_repeats_summary": structured_plan["expected_repeats_summary"],
            "expanded_steps": structured_plan["expanded_steps"],
        },
        "compliance": compliance,
        "comparisons": {
            "sport_match": _normalized(context.activity.sport_type) == _normalized(context.planned_session.sport_type),
            "recent_similar": recent_comparisons,
        },
        "weekly_context": weekly_context,
        "derived_flags": derived_flags,
        "scores": scores,
        "rule_thresholds": rules.exported_thresholds(),
    }


def _build_structured_plan(context: Any) -> dict[str, Any]:
    planned_steps = list(context.planned_session.steps or [])
    expanded_steps = expand_planned_steps(planned_steps)
    expanded_steps = _apply_inferred_targets(expanded_steps, context)
    return {
        "session_intent": detect_session_intent(context.planned_session, planned_steps),
        "expanded_steps": expanded_steps[:80],
        "primary_targets": build_primary_targets(expanded_steps),
        "block_structure": build_block_structure(expanded_steps)[:80],
        "expected_repeats_summary": build_expected_repeats_summary(planned_steps),
    }


def _apply_inferred_targets(expanded_steps: list[dict[str, Any]], context: Any) -> list[dict[str, Any]]:
    zone_rows = _zone_rows(context.athlete.hr_zones, context.planned_session.sport_type)
    for step in expanded_steps:
        if step.get("target_type"):
            continue
        inferred_zone = _infer_zone_from_notes(step.get("target_notes"), context.planned_session.target_notes, context.planned_session.description)
        if not inferred_zone:
            continue
        step["target_type"] = "hr"
        step["target_zone"] = inferred_zone
        step["target_source"] = "inferred"
        zone_range = _zone_range_by_name(zone_rows, inferred_zone)
        if zone_range:
            step["target_hr_min"] = zone_range["min"]
            step["target_hr_max"] = zone_range["max"]
            step["target_min"] = zone_range["min"]
            step["target_max"] = zone_range["max"]
    for step in expanded_steps:
        if step.get("target_type") and not step.get("target_source"):
            step["target_source"] = "explicit"
    return expanded_steps


def _infer_zone_from_notes(*notes: str | None) -> str | None:
    for note in notes:
        if not note:
            continue
        for token in note.replace(",", " ").replace("/", " ").split():
            normalized = token.strip().lower()
            if normalized.startswith("z") and len(normalized) >= 2 and normalized[1].isdigit():
                return f"Z{normalized[1]}"
    return None


def _build_planned_vs_actual(context: Any) -> dict[str, Any]:
    actual_duration_min = _seconds_to_minutes(context.activity.duration_sec)
    actual_distance_km = _meters_to_km(context.activity.distance_m)
    return {
        "duration": _comparison_metric(context.planned_session.expected_duration_min, actual_duration_min),
        "distance": _comparison_metric(context.planned_session.expected_distance_km, actual_distance_km),
        "elevation": _comparison_metric(context.planned_session.expected_elevation_gain_m, context.activity.elevation_gain_m),
    }


def _build_compliance_metrics(planned_vs_actual: dict[str, Any], laps: dict[str, Any]) -> dict[str, Any]:
    duration_score = closeness_score_from_delta_pct(planned_vs_actual["duration"]["delta_pct"])
    distance_score = closeness_score_from_delta_pct(planned_vs_actual["distance"]["delta_pct"])
    elevation_score = closeness_score_from_delta_pct(planned_vs_actual["elevation"]["delta_pct"])
    lap_alignment_score = laps.get("alignment_score")
    global_basic_score = average_scores([duration_score, distance_score, elevation_score])
    global_score = average_scores([global_basic_score, lap_alignment_score])
    return {
        "duration_score": duration_score,
        "distance_score": distance_score,
        "elevation_score": elevation_score,
        "lap_alignment_score": lap_alignment_score,
        "global_basic_score": global_basic_score,
        "global_score": global_score,
        "formula": {
            "duration_distance_elevation": "100 - abs(delta_pct), limitado a 0-100",
            "global_basic_score": "promedio simple de los componentes disponibles",
            "global_score": "promedio entre cumplimiento basico y alineacion por laps si existe",
        },
    }


def _build_heart_rate_metrics(context: Any) -> dict[str, Any] | None:
    avg_hr = context.activity.avg_hr
    max_hr = context.activity.max_hr
    athlete_max_hr = context.athlete.max_hr
    if avg_hr is None and max_hr is None and not context.activity_laps:
        return None

    avg_hr_pct_of_max = round(avg_hr / athlete_max_hr, 3) if avg_hr is not None and athlete_max_hr else None
    zone_distribution = _estimate_zone_distribution(
        context.activity_laps,
        context.activity.duration_sec,
        avg_value=avg_hr,
        zone_rows=_zone_rows(context.athlete.hr_zones, context.activity.sport_type),
        field_name="avg_hr",
    )
    drift = _estimate_cardiac_drift(context.activity_laps)
    session_target_comparison = None
    if context.planned_session.target_type == "hr":
        target_range = _zone_range_by_name(_zone_rows(context.athlete.hr_zones, context.planned_session.sport_type), context.planned_session.target_hr_zone)
        if target_range:
            session_target_comparison = range_target_score(avg_hr, target_range["min"], target_range["max"], rules.TARGET_MARGIN_HR)

    return {
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "avg_hr_pct_of_max": avg_hr_pct_of_max,
        "estimated_time_in_zones_sec": zone_distribution["time_by_zone_sec"],
        "estimated_pct_in_zones": zone_distribution["pct_by_zone"],
        "aerobic_control_label": _aerobic_control_label(avg_hr_pct_of_max),
        "cardiac_drift_ratio": drift["drift_ratio"],
        "cardiac_drift_bpm_delta": drift["hr_delta"],
        "session_target_comparison": session_target_comparison,
    }


def _build_pace_metrics(context: Any) -> dict[str, Any] | None:
    lap_paces = [lap.avg_pace_sec_km for lap in context.activity_laps if lap.avg_pace_sec_km is not None]
    avg_pace = context.activity.avg_pace_sec_km
    if avg_pace is None and not lap_paces:
        return None

    cv = _coefficient_of_variation(lap_paces)
    first_last = _first_last_third_delta(lap_paces)
    session_target_comparison = None
    if context.planned_session.target_type == "pace":
        target_range = _zone_range_by_name(_zone_rows(context.athlete.pace_zones, context.planned_session.sport_type), context.planned_session.target_pace_zone)
        if target_range:
            session_target_comparison = range_target_score(avg_pace, target_range["min"], target_range["max"], rules.TARGET_MARGIN_PACE_SEC)

    return {
        "avg_pace_sec_km": avg_pace,
        "lap_paces_sec_km": lap_paces,
        "stability_cv": cv,
        "stability_score": stability_score_from_cv(cv),
        "first_third_avg_pace_sec_km": first_last["first_avg"],
        "last_third_avg_pace_sec_km": first_last["last_avg"],
        "first_last_delta_sec_km": first_last["delta"],
        "session_target_comparison": session_target_comparison,
    }


def _build_power_metrics(context: Any) -> dict[str, Any] | None:
    lap_powers = [lap.avg_power for lap in context.activity_laps if lap.avg_power is not None]
    avg_power = context.activity.avg_power
    if avg_power is None and not lap_powers:
        return None

    cv = _coefficient_of_variation(lap_powers)
    session_target_comparison = None
    if context.planned_session.target_type == "power":
        target_range = _zone_range_by_name(_zone_rows(context.athlete.power_zones, context.planned_session.sport_type), context.planned_session.target_power_zone)
        if target_range:
            session_target_comparison = range_target_score(avg_power, target_range["min"], target_range["max"], rules.TARGET_MARGIN_POWER)

    return {
        "avg_power": avg_power,
        "lap_avg_power": lap_powers,
        "stability_cv": cv,
        "stability_score": stability_score_from_cv(cv),
        "normalized_power": context.activity.normalized_power,
        "session_target_comparison": session_target_comparison,
    }


def _build_cadence_metrics(context: Any) -> dict[str, Any] | None:
    lap_cadence = [lap.avg_cadence for lap in context.activity_laps if lap.avg_cadence is not None]
    avg_cadence = context.activity.avg_cadence
    if avg_cadence is None and not lap_cadence:
        return None

    cv = _coefficient_of_variation(lap_cadence)
    return {
        "avg_cadence": avg_cadence,
        "lap_avg_cadence": lap_cadence,
        "stability_cv": cv,
        "stability_score": stability_score_from_cv(cv),
        "quantitative_note": _cadence_note(avg_cadence, cv),
    }


def _build_elevation_metrics(context: Any, planned_vs_actual: dict[str, Any]) -> dict[str, Any]:
    return {
        "ascent_m": context.activity.elevation_gain_m,
        "descent_m": context.activity.elevation_loss_m,
        "comparison": planned_vs_actual["elevation"],
    }


def _build_lap_metrics(context: Any, structured_plan: dict[str, Any]) -> dict[str, Any]:
    planned_steps = context.planned_session.steps
    laps = context.activity_laps
    expanded_steps = structured_plan["expanded_steps"]
    structured_match = match_steps_to_laps(expanded_steps, laps) if expanded_steps or laps else {
        "matched_pairs": [],
        "unmatched_laps": [],
        "unmatched_steps": [],
        "matched_count": 0,
        "alignment_score": None,
        "interval_structure_detected": False,
        "structural_confidence": None,
    }

    matched_count = structured_match["matched_count"]
    alignment_score = structured_match.get("alignment_score")

    pairings: list[dict[str, Any]] = []
    for pairing in structured_match.get("matched_pairs", []):
        step = pairing["step"]
        lap = pairing["lap_summary"]
        pairings.append(
            {
                "planned_step_order": step["order"],
                "activity_lap_index": lap.get("index"),
                "planned_duration_sec": step["duration_sec"],
                "actual_duration_sec": lap.get("duration_sec"),
                "duration_delta_sec": _delta(step["duration_sec"], lap.get("duration_sec")),
                "duration_delta_pct": _delta_pct(step["duration_sec"], lap.get("duration_sec")),
                "planned_distance_m": step["distance_m"],
                "actual_distance_m": lap.get("distance_m"),
                "distance_delta_m": _delta(step["distance_m"], lap.get("distance_m")),
                "distance_delta_pct": _delta_pct(step["distance_m"], lap.get("distance_m")),
                "target_type": step["target_type"],
                "target_zone": step.get("target_zone"),
                "target_source": step.get("target_source"),
                "target_range": {"min": step.get("target_min"), "max": step.get("target_max")} if step.get("target_min") is not None or step.get("target_max") is not None else None,
                "target_evaluation": _evaluate_step_target(step, lap),
                "avg_hr": lap.get("avg_hr"),
                "avg_pace_sec_km": lap.get("avg_pace_sec_km"),
                "avg_power": lap.get("avg_power"),
                "avg_cadence": lap.get("avg_cadence"),
                "chosen_match_reason": pairing.get("chosen_match_reason"),
                "rejected_candidates": pairing.get("rejected_candidates"),
                "duration_penalty": pairing.get("duration_penalty"),
                "role_penalty": pairing.get("role_penalty"),
                "intensity_penalty": pairing.get("intensity_penalty"),
                "jump_penalty": pairing.get("jump_penalty"),
            }
        )

    return {
        "matched_count": matched_count,
        "missing_planned_steps": max(0, len(expanded_steps) - matched_count),
        "extra_laps": max(0, len(laps) - matched_count),
        "alignment_score": alignment_score,
        "pairs": pairings,
        "structured_match": structured_match,
    }


def _build_intensity_metrics(context: Any, structured_plan: dict[str, Any]) -> dict[str, Any]:
    target_type = context.planned_session.target_type
    target_zone = _session_target_zone_name(context)
    session_intent = structured_plan["session_intent"]
    structured_intent = session_intent in {"interval_training", "mixed_structured"}
    result = {
        "target_type": None if structured_intent else target_type,
        "target_zone": None if structured_intent else target_zone,
        "target_range": None,
        "actual_value": None,
        "actual_block": None,
        "target_compliance": None,
        "primary_targets": structured_plan["primary_targets"],
        "block_structure": structured_plan["block_structure"],
        "session_intent": session_intent,
        "global_target": "mixed" if structured_intent else target_type,
        "legacy_target_type": target_type,
        "legacy_target_zone": target_zone,
    }
    if not structured_intent and target_type == "hr":
        zone_rows = _zone_rows(context.athlete.hr_zones, context.planned_session.sport_type)
        target_range = _zone_range_by_name(zone_rows, context.planned_session.target_hr_zone)
        result["target_range"] = target_range
        result["actual_value"] = context.activity.avg_hr
        result["actual_block"] = "heart_rate"
        result["target_compliance"] = range_target_score(context.activity.avg_hr, target_range["min"], target_range["max"], rules.TARGET_MARGIN_HR) if target_range else None
    elif not structured_intent and target_type == "pace":
        zone_rows = _zone_rows(context.athlete.pace_zones, context.planned_session.sport_type)
        target_range = _zone_range_by_name(zone_rows, context.planned_session.target_pace_zone)
        result["target_range"] = target_range
        result["actual_value"] = context.activity.avg_pace_sec_km
        result["actual_block"] = "pace"
        result["target_compliance"] = range_target_score(context.activity.avg_pace_sec_km, target_range["min"], target_range["max"], rules.TARGET_MARGIN_PACE_SEC) if target_range else None
    elif not structured_intent and target_type == "power":
        zone_rows = _zone_rows(context.athlete.power_zones, context.planned_session.sport_type)
        target_range = _zone_range_by_name(zone_rows, context.planned_session.target_power_zone)
        result["target_range"] = target_range
        result["actual_value"] = context.activity.avg_power
        result["actual_block"] = "power"
        result["target_compliance"] = range_target_score(context.activity.avg_power, target_range["min"], target_range["max"], rules.TARGET_MARGIN_POWER) if target_range else None
    elif not structured_intent and target_type == "rpe":
        result["actual_block"] = "rpe"
    return result


def _build_recent_similar_comparisons(context: Any) -> dict[str, Any]:
    recent = context.recent_similar_sessions
    if not recent:
        return {
            "count": 0,
            "avg_duration_sec": None,
            "avg_distance_m": None,
            "avg_elevation_gain_m": None,
            "avg_hr": None,
            "avg_pace_sec_km": None,
            "current_vs_average": {},
        }

    avg_duration = _mean_known([item.duration_sec for item in recent])
    avg_distance = _mean_known([item.distance_m for item in recent])
    avg_elevation = _mean_known([item.elevation_gain_m for item in recent])
    avg_hr = _mean_known([item.avg_hr for item in recent])
    avg_pace = _mean_known([item.avg_pace_sec_km for item in recent])

    return {
        "count": len(recent),
        "avg_duration_sec": avg_duration,
        "avg_distance_m": avg_distance,
        "avg_elevation_gain_m": avg_elevation,
        "avg_hr": avg_hr,
        "avg_pace_sec_km": avg_pace,
        "current_vs_average": {
            "duration_delta_sec": _delta(avg_duration, context.activity.duration_sec),
            "distance_delta_m": _delta(avg_distance, context.activity.distance_m),
            "elevation_delta_m": _delta(avg_elevation, context.activity.elevation_gain_m),
            "avg_hr_delta": _delta(avg_hr, context.activity.avg_hr),
            "avg_pace_delta_sec_km": _delta(avg_pace, context.activity.avg_pace_sec_km),
        },
    }


def _build_weekly_context(context: Any) -> dict[str, Any]:
    weekly = context.weekly_summary
    duration_share_pct = None
    distance_share_pct = None
    elevation_share_pct = None
    if weekly.total_duration_sec and context.activity.duration_sec is not None:
        duration_share_pct = round((context.activity.duration_sec / weekly.total_duration_sec) * 100.0, 1)
    if weekly.total_distance_m and context.activity.distance_m is not None:
        distance_share_pct = round((context.activity.distance_m / weekly.total_distance_m) * 100.0, 1)
    if weekly.total_elevation_gain_m and context.activity.elevation_gain_m is not None:
        elevation_share_pct = round((context.activity.elevation_gain_m / weekly.total_elevation_gain_m) * 100.0, 1)

    return {
        "week_start": weekly.week_start.isoformat(),
        "week_end": weekly.week_end.isoformat(),
        "activity_count": weekly.activity_count,
        "planned_session_count": weekly.planned_session_count,
        "matched_session_count": weekly.matched_session_count,
        "completed_ratio_pct": weekly.completed_ratio_pct,
        "total_duration_sec": weekly.total_duration_sec,
        "total_distance_m": weekly.total_distance_m,
        "total_elevation_gain_m": weekly.total_elevation_gain_m,
        "activities_by_sport": weekly.activities_by_sport,
        "session_duration_share_pct": duration_share_pct,
        "session_distance_share_pct": distance_share_pct,
        "session_elevation_share_pct": elevation_share_pct,
    }


def _build_flags(
    context: Any,
    planned_vs_actual: dict[str, Any],
    heart_rate: dict[str, Any] | None,
    pace: dict[str, Any] | None,
    intensity: dict[str, Any],
    laps: dict[str, Any],
    structured_plan: dict[str, Any],
    block_analysis: list[dict[str, Any]],
) -> dict[str, Any]:
    duration_ratio = planned_vs_actual["duration"]["actual_to_planned_ratio"]
    distance_ratio = planned_vs_actual["distance"]["actual_to_planned_ratio"]
    elevation_ratio = planned_vs_actual["elevation"]["actual_to_planned_ratio"]

    cardiac_drift_flag = False
    if heart_rate and heart_rate.get("cardiac_drift_ratio") is not None:
        pace_cv = pace.get("stability_cv") if pace else None
        cardiac_drift_flag = heart_rate["cardiac_drift_ratio"] >= rules.CARDIAC_DRIFT_HR_DELTA_RATIO and (
            pace_cv is None or pace_cv <= rules.CARDIAC_DRIFT_PACE_CV_MAX
        )

    heart_rate_high_flag = False
    if heart_rate and heart_rate.get("avg_hr_pct_of_max") is not None:
        heart_rate_high_flag = heart_rate["avg_hr_pct_of_max"] >= rules.HIGH_AVG_HR_PCT_OF_MAX
    if intensity.get("target_type") == "hr" and intensity.get("target_compliance"):
        heart_rate_high_flag = heart_rate_high_flag or intensity["target_compliance"]["status"] == "above_range"

    pace_instability_flag = bool(pace and pace.get("stability_cv") is not None and pace["stability_cv"] >= rules.PACE_INSTABILITY_CV_THRESHOLD)
    structured_flags = derive_structured_flags(structured_plan["session_intent"], laps.get("structured_match", {}), block_analysis)
    if structured_flags.get("expected_variability"):
        pace_instability_flag = False
    possible_heat_impact_flag = bool(context.activity.avg_temperature_c is not None and context.activity.avg_temperature_c >= rules.HEAT_IMPACT_TEMP_C)
    hydration_risk_flag = bool(
        (context.activity.duration_sec or 0) >= rules.HYDRATION_RISK_DURATION_SEC
        and (context.activity.avg_temperature_c or 0) >= rules.HYDRATION_RISK_TEMP_C
    )
    lap_total = laps["matched_count"] + laps["missing_planned_steps"] + laps["extra_laps"]
    lap_coverage = (laps["matched_count"] / lap_total) if lap_total else 1.0
    manual_review_needed = bool(
        _normalized(context.activity.sport_type) != _normalized(context.planned_session.sport_type)
        or lap_coverage < rules.LAP_MATCH_MIN_COVERAGE_FOR_REVIEW
    )

    return {
        "duration_over_target_flag": bool(duration_ratio is not None and duration_ratio > rules.DURATION_OVER_TARGET_RATIO),
        "distance_over_target_flag": bool(distance_ratio is not None and distance_ratio > rules.DISTANCE_OVER_TARGET_RATIO),
        "elevation_over_target_flag": bool(elevation_ratio is not None and elevation_ratio > rules.ELEVATION_OVER_TARGET_RATIO),
        "heart_rate_high_flag": heart_rate_high_flag,
        "pace_instability_flag": pace_instability_flag,
        "possible_heat_impact_flag": possible_heat_impact_flag,
        "heat_impact_flag": possible_heat_impact_flag,
        "cardiac_drift_flag": cardiac_drift_flag,
        "hydration_risk_flag": hydration_risk_flag,
        "manual_review_needed": manual_review_needed,
        **structured_flags,
    }


def _build_scores(
    context: Any,
    compliance: dict[str, Any],
    heart_rate: dict[str, Any] | None,
    pace: dict[str, Any] | None,
    power: dict[str, Any] | None,
    cadence: dict[str, Any] | None,
    intensity: dict[str, Any],
    laps: dict[str, Any],
    structured_plan: dict[str, Any],
    block_analysis: list[dict[str, Any]],
) -> dict[str, Any]:
    compliance_score = compliance["global_score"]
    structured_execution = compute_execution_score_structured(laps.get("structured_match", {}), block_analysis)
    execution_score = structured_execution["execution_score"]
    if execution_score is None:
        execution_score = average_scores(
            [
                laps.get("alignment_score"),
                pace.get("stability_score") if pace else None,
                power.get("stability_score") if power else None,
                cadence.get("stability_score") if cadence else None,
            ]
        )

    hr_control_component = None
    if heart_rate and heart_rate.get("avg_hr_pct_of_max") is not None:
        hr_control_component = 100.0 if heart_rate["avg_hr_pct_of_max"] <= rules.AEROBIC_CONTROL_MODERATE_MAX else 65.0
    target_control_component = intensity.get("target_compliance", {}).get("score") if intensity.get("target_compliance") else None
    drift_control_component = None
    if heart_rate and heart_rate.get("cardiac_drift_ratio") is not None:
        drift_control_component = 100.0 if heart_rate["cardiac_drift_ratio"] < rules.CARDIAC_DRIFT_HR_DELTA_RATIO else 60.0
    control_score = average_scores([hr_control_component, target_control_component, drift_control_component])

    duration_component = min(100.0, (context.activity.duration_sec / 7200.0) * 100.0) if context.activity.duration_sec is not None else None
    elevation_component = min(100.0, (context.activity.elevation_gain_m / 1000.0) * 100.0) if context.activity.elevation_gain_m is not None else None
    training_load_component = min(100.0, float(context.activity.training_load)) if context.activity.training_load is not None else None
    training_effect_total = None
    if context.activity.training_effect_aerobic is not None or context.activity.training_effect_anaerobic is not None:
        training_effect_total = ((context.activity.training_effect_aerobic or 0.0) + (context.activity.training_effect_anaerobic or 0.0)) * 10.0
    heat_component = 75.0 if (context.activity.avg_temperature_c or 0) >= rules.HEAT_IMPACT_TEMP_C else None
    fatigue_score = average_scores([duration_component, elevation_component, training_load_component, training_effect_total, heat_component])

    structural_adherence_score = average_scores(
        [
            laps.get("alignment_score"),
            (laps.get("structured_match") or {}).get("structural_confidence"),
        ]
    )
    physiological_adherence_score = average_scores([block.get("score") for block in block_analysis if block.get("score") is not None])

    return {
        "compliance_score": compliance_score,
        "execution_score": execution_score,
        "execution_score_details": structured_execution,
        "structural_adherence_score": structural_adherence_score,
        "physiological_adherence_score": physiological_adherence_score,
        "control_score": control_score,
        "fatigue_score": fatigue_score,
        "formula": {
            "compliance_score": "promedio entre cumplimiento basico y alineacion por laps cuando exista",
            "execution_score": "estabilidad por roles (trabajo/recuperacion) y alineacion de estructura si aplica",
            "control_score": "promedio entre control de FC, cumplimiento de target e indicador simple de drift",
            "fatigue_score": "promedio de duracion, desnivel, carga, training effect y calor/temperatura si existen",
        },
    }


def _comparison_metric(planned: float | None, actual: float | None) -> dict[str, float | None]:
    delta_abs = None if planned is None or actual is None else round(actual - planned, 2)
    delta_pct = None if planned is None or actual is None or planned == 0 else round(((actual - planned) / planned) * 100.0, 1)
    ratio = None if planned is None or actual is None or planned == 0 else round(actual / planned, 3)
    return {
        "planned": planned,
        "actual": actual,
        "delta_abs": delta_abs,
        "delta_pct": delta_pct,
        "actual_to_planned_ratio": ratio,
    }


def _estimate_zone_distribution(laps: list[Any], total_duration_sec: int | None, *, avg_value: float | int | None, zone_rows: list[dict[str, Any]], field_name: str) -> dict[str, Any]:
    if not zone_rows:
        return {"time_by_zone_sec": {}, "pct_by_zone": {}}

    time_by_zone: dict[str, int] = {str(row.get("name")): 0 for row in zone_rows}
    used_duration = 0
    for lap in laps:
        lap_value = getattr(lap, field_name, None)
        lap_duration = lap.duration_sec or 0
        if lap_value is None or lap_duration <= 0:
            continue
        zone_name = _zone_name_for_value(zone_rows, float(lap_value))
        if zone_name:
            time_by_zone[zone_name] = time_by_zone.get(zone_name, 0) + int(lap_duration)
            used_duration += int(lap_duration)

    if used_duration == 0 and avg_value is not None and total_duration_sec:
        zone_name = _zone_name_for_value(zone_rows, float(avg_value))
        if zone_name:
            time_by_zone[zone_name] = int(total_duration_sec)
            used_duration = int(total_duration_sec)

    pct_by_zone = {
        zone_name: round((seconds / used_duration) * 100.0, 1)
        for zone_name, seconds in time_by_zone.items()
        if used_duration > 0 and seconds > 0
    }
    time_by_zone = {key: value for key, value in time_by_zone.items() if value > 0}
    return {"time_by_zone_sec": time_by_zone, "pct_by_zone": pct_by_zone}


def _aerobic_control_label(avg_hr_pct_of_max: float | None) -> str | None:
    if avg_hr_pct_of_max is None:
        return None
    if avg_hr_pct_of_max <= rules.AEROBIC_CONTROL_EASY_MAX:
        return "controlado"
    if avg_hr_pct_of_max <= rules.AEROBIC_CONTROL_MODERATE_MAX:
        return "moderado"
    return "alto"


def _estimate_cardiac_drift(laps: list[Any]) -> dict[str, float | None]:
    hr_values = [lap.avg_hr for lap in laps if lap.avg_hr is not None]
    if len(hr_values) < 3:
        return {"drift_ratio": None, "hr_delta": None}
    thirds = _split_thirds(hr_values)
    if not thirds["first"] or not thirds["last"]:
        return {"drift_ratio": None, "hr_delta": None}
    first_avg = mean(thirds["first"])
    last_avg = mean(thirds["last"])
    if first_avg <= 0:
        return {"drift_ratio": None, "hr_delta": None}
    delta = last_avg - first_avg
    return {"drift_ratio": round(delta / first_avg, 3), "hr_delta": round(delta, 1)}


def _first_last_third_delta(values: list[float]) -> dict[str, float | None]:
    if len(values) < 3:
        return {"first_avg": None, "last_avg": None, "delta": None}
    thirds = _split_thirds(values)
    if not thirds["first"] or not thirds["last"]:
        return {"first_avg": None, "last_avg": None, "delta": None}
    first_avg = round(mean(thirds["first"]), 2)
    last_avg = round(mean(thirds["last"]), 2)
    return {"first_avg": first_avg, "last_avg": last_avg, "delta": round(last_avg - first_avg, 2)}


def _evaluate_step_target(step: Any, lap: Any) -> dict[str, Any] | None:
    target_type = step["target_type"] if isinstance(step, dict) else step.target_type
    if target_type == "hr":
        return range_target_score(_get_lap_value(lap, "avg_hr"), _get_step_value(step, "target_hr_min"), _get_step_value(step, "target_hr_max"), rules.TARGET_MARGIN_HR)
    if target_type == "pace":
        return range_target_score(
            _get_lap_value(lap, "avg_pace_sec_km"),
            _get_step_value(step, "target_pace_min_sec_km"),
            _get_step_value(step, "target_pace_max_sec_km"),
            rules.TARGET_MARGIN_PACE_SEC,
            higher_is_better=True,
        )
    if target_type == "power":
        return range_target_score(_get_lap_value(lap, "avg_power"), _get_step_value(step, "target_power_min"), _get_step_value(step, "target_power_max"), rules.TARGET_MARGIN_POWER)
    if target_type == "rpe":
        return {"score": None, "status": "not_evaluable", "within_range": None, "delta_to_range": None}
    return None


def _get_step_value(step: Any, field: str) -> Any:
    if isinstance(step, dict):
        return step.get(field)
    return getattr(step, field, None)


def _get_lap_value(lap: Any, field: str) -> Any:
    if isinstance(lap, dict):
        return lap.get(field)
    return getattr(lap, field, None)


def _session_target_zone_name(context: Any) -> str | None:
    if context.planned_session.target_type == "hr":
        return context.planned_session.target_hr_zone
    if context.planned_session.target_type == "pace":
        return context.planned_session.target_pace_zone
    if context.planned_session.target_type == "power":
        return context.planned_session.target_power_zone
    if context.planned_session.target_type == "rpe":
        return context.planned_session.target_rpe_zone
    return None


def _zone_rows(zone_payload: dict[str, Any] | None, sport_type: str | None) -> list[dict[str, Any]]:
    if not zone_payload:
        return []
    normalized_sport = _normalized(sport_type)
    if normalized_sport and normalized_sport in zone_payload and isinstance(zone_payload[normalized_sport], list):
        return zone_payload[normalized_sport]
    if "general" in zone_payload and isinstance(zone_payload["general"], list):
        return zone_payload["general"]
    first_value = next((value for value in zone_payload.values() if isinstance(value, list)), [])
    return first_value


def _zone_range_by_name(zone_rows: list[dict[str, Any]], zone_name: str | None) -> dict[str, Any] | None:
    if not zone_name:
        return None
    for row in zone_rows:
        if str(row.get("name")) == zone_name:
            return {"name": zone_name, "min": _as_float(row.get("min")), "max": _as_float(row.get("max"))}
    return None


def _zone_name_for_value(zone_rows: list[dict[str, Any]], value: float) -> str | None:
    for row in zone_rows:
        minimum = _as_float(row.get("min"))
        maximum = _as_float(row.get("max"))
        if minimum is not None and value < minimum:
            continue
        if maximum is not None and value > maximum:
            continue
        return str(row.get("name"))
    return None


def _coefficient_of_variation(values: list[float | int]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if len(numeric) < 2:
        return None
    mean_value = mean(numeric)
    if mean_value == 0:
        return None
    return round(pstdev(numeric) / mean_value, 4)


def _split_thirds(values: list[float | int]) -> dict[str, list[float]]:
    if not values:
        return {"first": [], "middle": [], "last": []}
    size = max(1, len(values) // 3)
    first = [float(v) for v in values[:size]]
    last = [float(v) for v in values[-size:]]
    middle = [float(v) for v in values[size:-size]] if len(values) > (size * 2) else []
    return {"first": first, "middle": middle, "last": last}


def _cadence_note(avg_cadence: float | None, cv: float | None) -> str | None:
    if avg_cadence is None:
        return None
    if cv is None:
        return "cadencia disponible sin suficientes laps para estabilidad"
    if cv < rules.CADENCE_INSTABILITY_CV_THRESHOLD:
        return "cadencia estable"
    return "cadencia variable"


def _mean_known(values: list[float | int | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(mean(usable), 2)


def _delta(reference: float | int | None, actual: float | int | None) -> float | None:
    if reference is None or actual is None:
        return None
    return round(float(actual) - float(reference), 2)


def _delta_pct(reference: float | int | None, actual: float | int | None) -> float | None:
    if reference is None or actual is None or float(reference) == 0:
        return None
    return round(((float(actual) - float(reference)) / float(reference)) * 100.0, 1)


def _seconds_to_minutes(value: int | None) -> float | None:
    if value is None:
        return None
    return round(value / 60.0, 1)


def _meters_to_km(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 1000.0, 2)


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalized(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower().replace("-", "_").replace(" ", "_")
