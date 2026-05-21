from __future__ import annotations

from datetime import date
from unicodedata import normalize

from app.services.analysis_v2.metrics import compute_session_metrics
from app.services.analysis_v2.narrative import _build_fallback_output
from app.services.analysis_v2.structured import detect_session_intent, expand_planned_steps, match_steps_to_laps
from app.services.analysis_v2.session_analysis_service import (
    ActivityContext,
    ActivityLapContext,
    AthleteProfileContext,
    PlannedSessionContext,
    PlannedStepContext,
    SessionAnalysisContext,
    WeeklySummaryContext,
)


def _make_step(
    order: int,
    *,
    repeat_count: int | None = None,
    step_type: str = "work",
    target_type: str | None = None,
    target_hr_zone: str | None = None,
    target_hr_min: int | None = None,
    target_hr_max: int | None = None,
    target_pace_zone: str | None = None,
    target_pace_min: int | None = None,
    target_pace_max: int | None = None,
    duration_sec: int | None = None,
    distance_m: int | None = None,
    incline_pct: float | None = None,
) -> PlannedStepContext:
    return PlannedStepContext(
        id=order,
        order=order,
        step_type=step_type,
        repeat_count=repeat_count,
        duration_sec=duration_sec,
        distance_m=distance_m,
        target_type=target_type,
        target_hr_zone=target_hr_zone,
        target_hr_min=target_hr_min,
        target_hr_max=target_hr_max,
        target_power_zone=None,
        target_power_min=None,
        target_power_max=None,
        target_pace_zone=target_pace_zone,
        target_pace_min_sec_km=target_pace_min,
        target_pace_max_sec_km=target_pace_max,
        target_rpe_zone=None,
        target_cadence_min=None,
        target_cadence_max=None,
        incline_pct=incline_pct,
        target_notes=None,
    )


def _make_lap(
    index: int,
    *,
    duration_sec: int,
    distance_m: float,
    avg_hr: int | None,
    avg_pace_sec_km: float | None,
    max_hr: int | None = None,
    avg_cadence: float | None = None,
    max_cadence: float | None = None,
) -> ActivityLapContext:
    return ActivityLapContext(
        index=index,
        name=None,
        lap_type=None,
        start_time=None,
        duration_sec=duration_sec,
        moving_duration_sec=duration_sec,
        distance_m=distance_m,
        elevation_gain_m=None,
        elevation_loss_m=None,
        avg_hr=avg_hr,
        max_hr=max_hr,
        avg_pace_sec_km=avg_pace_sec_km,
        avg_power=None,
        max_power=None,
        avg_cadence=avg_cadence,
        max_cadence=max_cadence,
    )


def _make_context(steps: list[PlannedStepContext], laps: list[ActivityLapContext]) -> SessionAnalysisContext:
    return SessionAnalysisContext(
        athlete=AthleteProfileContext(
            id=1,
            name="Pablo",
            primary_sport="running",
            max_hr=190,
            resting_hr=50,
            lactate_threshold_hr=None,
            running_threshold_pace_sec_km=None,
            cycling_ftp=None,
            vo2max=None,
            hr_zones=None,
            pace_zones=None,
            power_zones=None,
            rpe_zones=None,
        ),
        planned_session=PlannedSessionContext(
            id=1,
            athlete_id=1,
            training_day_id=1,
            training_plan_id=None,
            session_order=1,
            session_date=date(2026, 4, 7),
            plan_name=None,
            title="Sesion intervalos",
            sport_type="running",
            discipline_variant=None,
            modality=None,
            session_type=None,
            description=None,
            target_notes=None,
            planned_start_time=None,
            expected_duration_min=60,
            expected_distance_km=10.0,
            expected_elevation_gain_m=None,
            strength_focus=None,
            strength_rpe=None,
            target_type=None,
            target_hr_zone=None,
            target_pace_zone=None,
            target_power_zone=None,
            target_rpe_zone=None,
            is_key_session=False,
            day_type=None,
            day_notes=None,
            goal=None,
            steps=steps,
        ),
        activity=ActivityContext(
            id=1,
            athlete_id=1,
            garmin_activity_id=1,
            title="Actividad",
            sport_type="running",
            discipline_variant=None,
            modality=None,
            start_time=None,
            end_time=None,
            local_date=date(2026, 4, 7),
            duration_sec=3600,
            moving_duration_sec=3550,
            distance_m=10000,
            elevation_gain_m=None,
            elevation_loss_m=None,
            avg_hr=155,
            max_hr=175,
            avg_power=None,
            max_power=None,
            normalized_power=None,
            avg_speed_mps=None,
            max_speed_mps=None,
            avg_pace_sec_km=330,
            avg_cadence=None,
            max_cadence=None,
            training_effect_aerobic=None,
            training_effect_anaerobic=None,
            training_load=None,
            calories=None,
            avg_temperature_c=None,
            start_lat=None,
            start_lon=None,
            device_name=None,
        ),
        activity_laps=laps,
        weather=None,
        health=None,
        recent_similar_sessions=[],
        weekly_summary=WeeklySummaryContext(
            week_start=date(2026, 4, 6),
            week_end=date(2026, 4, 12),
            activity_count=1,
            total_duration_sec=3600,
            total_distance_m=10000,
            total_elevation_gain_m=0,
            activities_by_sport={"running": 1},
            planned_session_count=1,
            matched_session_count=1,
            completed_ratio_pct=100.0,
        ),
    )


def _set_modality(context: SessionAnalysisContext, planned: str | None, activity: str | None) -> SessionAnalysisContext:
    context.planned_session.modality = planned
    context.activity.modality = activity
    return context


def test_detect_session_intent_interval_mixed():
    steps = [
        _make_step(1, step_type="warmup", target_type="pace", target_pace_zone="z3", duration_sec=600),
        _make_step(2, repeat_count=4, target_type="pace", target_pace_zone="z4", distance_m=1500),
        _make_step(3, repeat_count=4, target_type="hr", target_hr_zone="z2", duration_sec=90),
        _make_step(4, repeat_count=2, target_type="pace", target_pace_zone="z3", duration_sec=720),
        _make_step(5, repeat_count=2, target_type="hr", target_hr_zone="z2", duration_sec=90),
    ]
    intent = detect_session_intent(_make_context(steps, []).planned_session, steps)
    assert intent in {"mixed_structured", "interval_training"}


def test_expand_planned_steps_with_repeats():
    steps = [
        _make_step(1, target_type="pace", target_pace_zone="z3", duration_sec=600),
        _make_step(2, repeat_count=3, target_type="pace", target_pace_zone="z4", distance_m=400),
        _make_step(3, repeat_count=3, target_type="hr", target_hr_zone="z2", duration_sec=60),
    ]
    expanded = expand_planned_steps(steps)
    assert len(expanded) == 1 + (3 * 2)


def test_match_steps_to_laps_structured():
    steps = [
        _make_step(1, repeat_count=2, target_type="pace", target_pace_zone="z4", distance_m=400),
        _make_step(2, repeat_count=2, target_type="hr", target_hr_zone="z2", duration_sec=60),
    ]
    expanded = expand_planned_steps(steps)
    laps = [
        _make_lap(1, duration_sec=100, distance_m=400, avg_hr=165, avg_pace_sec_km=260),
        _make_lap(2, duration_sec=60, distance_m=100, avg_hr=120, avg_pace_sec_km=None),
        _make_lap(3, duration_sec=100, distance_m=400, avg_hr=168, avg_pace_sec_km=258),
        _make_lap(4, duration_sec=60, distance_m=100, avg_hr=118, avg_pace_sec_km=None),
    ]
    match = match_steps_to_laps(expanded, laps)
    assert match["matched_count"] == len(expanded)
    assert match["unmatched_laps"] == []
    assert match["alignment_score"] is not None
    assert match["alignment_score"] >= 85


def test_match_steps_to_laps_prefers_simple_sequential_pattern_with_cooldown():
    steps = [
        _make_step(1, step_type="warmup", duration_sec=900),
        _make_step(2, step_type="work", duration_sec=300, target_type="pace", target_pace_zone="z4", target_pace_min=285, target_pace_max=320),
        _make_step(3, step_type="recovery", duration_sec=120, target_type="hr", target_hr_zone="z1", target_hr_min=105, target_hr_max=125),
        _make_step(4, step_type="work", duration_sec=300, target_type="pace", target_pace_zone="z4", target_pace_min=285, target_pace_max=320),
        _make_step(5, step_type="recovery", duration_sec=120, target_type="hr", target_hr_zone="z1", target_hr_min=105, target_hr_max=125),
        _make_step(6, step_type="work", duration_sec=300, target_type="pace", target_pace_zone="z4", target_pace_min=285, target_pace_max=320),
        _make_step(7, step_type="recovery", duration_sec=120, target_type="hr", target_hr_zone="z1", target_hr_min=105, target_hr_max=125),
        _make_step(8, step_type="work", duration_sec=300, target_type="pace", target_pace_zone="z4", target_pace_min=285, target_pace_max=320),
        _make_step(9, step_type="recovery", duration_sec=120, target_type="hr", target_hr_zone="z1", target_hr_min=105, target_hr_max=125),
        _make_step(10, step_type="cooldown", duration_sec=600, target_type="hr", target_hr_zone="z1", target_hr_min=105, target_hr_max=130),
    ]
    expanded = expand_planned_steps(steps)
    laps = [
        _make_lap(1, duration_sec=900, distance_m=2300, avg_hr=128, avg_pace_sec_km=391),
        _make_lap(2, duration_sec=300, distance_m=980, avg_hr=164, avg_pace_sec_km=306),
        _make_lap(3, duration_sec=120, distance_m=190, avg_hr=119, avg_pace_sec_km=632),
        _make_lap(4, duration_sec=300, distance_m=990, avg_hr=166, avg_pace_sec_km=303),
        _make_lap(5, duration_sec=120, distance_m=195, avg_hr=118, avg_pace_sec_km=615),
        _make_lap(6, duration_sec=300, distance_m=1000, avg_hr=167, avg_pace_sec_km=300),
        _make_lap(7, duration_sec=120, distance_m=188, avg_hr=117, avg_pace_sec_km=638),
        _make_lap(8, duration_sec=300, distance_m=995, avg_hr=168, avg_pace_sec_km=302),
        _make_lap(9, duration_sec=120, distance_m=185, avg_hr=116, avg_pace_sec_km=649),
        _make_lap(10, duration_sec=660, distance_m=1500, avg_hr=121, avg_pace_sec_km=440),
    ]
    match = match_steps_to_laps(expanded, laps)
    assert match["matched_count"] == 10
    assert match["unmatched_laps"] == []
    assert match["unmatched_steps"] == []
    assert match["alignment_score"] is not None
    assert match["alignment_score"] >= 90
    assert match["matched_pairs"][-1]["step"]["role"] == "cooldown"
    assert match["matched_pairs"][-1]["lap_index"] == 9
    assert match["matched_pairs"][-1]["chosen_match_reason"]
    assert isinstance(match["matched_pairs"][-1]["rejected_candidates"], list)


def test_compute_metrics_interval_expected_variability():
    steps = [
        _make_step(1, target_type="pace", target_pace_zone="z3", duration_sec=600),
        _make_step(2, repeat_count=3, target_type="pace", target_pace_zone="z4", distance_m=400),
        _make_step(3, repeat_count=3, target_type="hr", target_hr_zone="z2", duration_sec=60),
    ]
    laps = [
        _make_lap(1, duration_sec=600, distance_m=2000, avg_hr=150, avg_pace_sec_km=320),
        _make_lap(2, duration_sec=90, distance_m=400, avg_hr=170, avg_pace_sec_km=250),
        _make_lap(3, duration_sec=60, distance_m=100, avg_hr=120, avg_pace_sec_km=None),
        _make_lap(4, duration_sec=92, distance_m=400, avg_hr=172, avg_pace_sec_km=248),
        _make_lap(5, duration_sec=60, distance_m=100, avg_hr=118, avg_pace_sec_km=None),
        _make_lap(6, duration_sec=95, distance_m=400, avg_hr=173, avg_pace_sec_km=247),
        _make_lap(7, duration_sec=60, distance_m=100, avg_hr=117, avg_pace_sec_km=None),
    ]
    context = _make_context(steps, laps)
    metrics = compute_session_metrics(context)
    flags = metrics["derived_flags"]
    assert flags["expected_variability"] is True
    assert flags["pace_instability_flag"] is False


def test_compute_metrics_continuous_keeps_instability_flag():
    steps = [_make_step(1, target_type="pace", target_pace_zone="z2", duration_sec=3600)]
    laps = [
        _make_lap(1, duration_sec=1200, distance_m=4000, avg_hr=145, avg_pace_sec_km=310),
        _make_lap(2, duration_sec=1200, distance_m=3900, avg_hr=150, avg_pace_sec_km=325),
        _make_lap(3, duration_sec=1200, distance_m=3800, avg_hr=152, avg_pace_sec_km=340),
    ]
    context = _make_context(steps, laps)
    metrics = compute_session_metrics(context)
    flags = metrics["derived_flags"]
    assert flags["expected_variability"] is False


def test_recovery_out_of_range_penalizes_scores():
    steps = [
        _make_step(1, target_type="pace", target_pace_zone="z4", distance_m=1000),
        _make_step(2, target_type="hr", target_hr_zone="z2", target_hr_min=107, target_hr_max=125, duration_sec=90),
        _make_step(3, target_type="pace", target_pace_zone="z4", distance_m=1000),
        _make_step(4, target_type="hr", target_hr_zone="z2", target_hr_min=107, target_hr_max=125, duration_sec=90),
    ]
    laps = [
        _make_lap(1, duration_sec=240, distance_m=1000, avg_hr=170, avg_pace_sec_km=240),
        _make_lap(2, duration_sec=90, distance_m=150, avg_hr=150, avg_pace_sec_km=None),
        _make_lap(3, duration_sec=245, distance_m=1000, avg_hr=172, avg_pace_sec_km=238),
        _make_lap(4, duration_sec=90, distance_m=150, avg_hr=148, avg_pace_sec_km=None),
    ]
    context = _make_context(steps, laps)
    metrics = compute_session_metrics(context)
    flags = metrics["derived_flags"]
    scores = metrics["scores"]
    assert flags["recovery_block_not_effective_flag"] is True
    assert scores["physiological_adherence_score"] is not None


def test_short_note_recovery_messages():
    steps = [
        _make_step(1, target_type="pace", target_pace_zone="z4", distance_m=1000),
        _make_step(2, target_type="hr", target_hr_zone="z2", target_hr_min=107, target_hr_max=125, duration_sec=90),
    ]
    laps = [
        _make_lap(1, duration_sec=240, distance_m=1000, avg_hr=170, avg_pace_sec_km=240),
        _make_lap(2, duration_sec=90, distance_m=150, avg_hr=150, avg_pace_sec_km=None),
    ]
    context = _make_context(steps, laps)
    metrics = compute_session_metrics(context)
    block_notes = [block["short_note"] for block in metrics["block_analysis"]]
    normalized_notes = [normalize("NFKD", note).encode("ascii", "ignore").decode("ascii") for note in block_notes if note]
    assert any("recuperacion" in note for note in normalized_notes)


def test_pace_direction_fast_vs_slow():
    steps = [
        _make_step(1, target_type="pace", target_pace_zone="z3", target_pace_min=320, target_pace_max=340, distance_m=1000),
        _make_step(2, target_type="pace", target_pace_zone="z3", target_pace_min=320, target_pace_max=340, distance_m=1000),
    ]
    laps = [
        _make_lap(1, duration_sec=300, distance_m=1000, avg_hr=160, avg_pace_sec_km=300),
        _make_lap(2, duration_sec=360, distance_m=1000, avg_hr=150, avg_pace_sec_km=360),
    ]
    context = _make_context(steps, laps)
    metrics = compute_session_metrics(context)
    notes = [block["short_note"] for block in metrics["block_analysis"]]
    assert any("exigente" in (note or "") for note in notes)
    assert any("debajo" in (note or "") for note in notes)


def test_hr_work_above_target_uses_fine_grained_short_note():
    steps = [_make_step(1, target_type="hr", target_hr_min=125, target_hr_max=140, duration_sec=600)]
    laps = [_make_lap(1, duration_sec=600, distance_m=2000, avg_hr=147, avg_pace_sec_km=330)]
    context = _make_context(steps, laps)

    metrics = compute_session_metrics(context)

    assert metrics["block_analysis"][0]["short_note"] == "claramente por encima del objetivo"


def test_infer_zone_from_target_notes():
    steps = [
        _make_step(1, target_type=None, target_hr_zone=None, duration_sec=600),
        _make_step(2, target_type=None, target_hr_zone=None, duration_sec=600),
    ]
    steps[0].target_notes = "Z2"
    steps[1].target_notes = "Z3"
    context = _make_context(steps, [])
    context.athlete.hr_zones = {
        "general": [
            {"name": "Z2", "min": 107, "max": 125},
            {"name": "Z3", "min": 126, "max": 145},
        ]
    }
    metrics = compute_session_metrics(context)
    block_analysis = metrics["block_analysis"]
    assert block_analysis[0]["target_type"] == "hr"
    assert block_analysis[0]["target_zone"] == "Z2"
    assert block_analysis[1]["target_zone"] == "Z3"


def test_inferred_targets_used_in_lap_pairs():
    steps = [_make_step(1, target_type=None, target_hr_zone=None, duration_sec=600)]
    steps[0].target_notes = "Z2"
    laps = [_make_lap(1, duration_sec=600, distance_m=2000, avg_hr=120, avg_pace_sec_km=300)]
    context = _make_context(steps, laps)
    context.athlete.hr_zones = {"general": [{"name": "Z2", "min": 107, "max": 125}]}
    metrics = compute_session_metrics(context)
    pair = metrics["laps"]["pairs"][0]
    assert pair["target_source"] == "inferred"
    assert pair["target_evaluation"] is not None


def test_explicit_target_precedence():
    steps = [_make_step(1, target_type="pace", target_pace_zone="z3", target_pace_min=320, target_pace_max=340, duration_sec=600)]
    steps[0].target_notes = "Z2"
    laps = [_make_lap(1, duration_sec=600, distance_m=2000, avg_hr=120, avg_pace_sec_km=330)]
    context = _make_context(steps, laps)
    metrics = compute_session_metrics(context)
    pair = metrics["laps"]["pairs"][0]
    assert pair["target_source"] == "explicit"


def test_custom_explicit_targets_flow_to_analysis_v2():
    steps = [
        _make_step(1, target_type="hr", target_hr_min=151, target_hr_max=155, duration_sec=600),
        _make_step(2, target_type="pace", target_pace_min=300, target_pace_max=310, duration_sec=360),
    ]
    laps = [
        _make_lap(1, duration_sec=600, distance_m=1800, avg_hr=153, avg_pace_sec_km=330),
        _make_lap(2, duration_sec=360, distance_m=1180, avg_hr=166, avg_pace_sec_km=305),
    ]
    context = _make_context(steps, laps)
    metrics = compute_session_metrics(context)
    pairs = metrics["laps"]["pairs"]
    block_analysis = metrics["block_analysis"]

    assert pairs[0]["target_type"] == "hr"
    assert pairs[0]["target_zone"] is None
    assert pairs[0]["target_range"] == {"min": 151, "max": 155}
    assert pairs[0]["target_evaluation"]["within_range"] is True

    assert pairs[1]["target_type"] == "pace"
    assert pairs[1]["target_range"] == {"min": 300, "max": 310}
    assert pairs[1]["target_evaluation"]["within_range"] is True

    assert block_analysis[0]["planned_target_min"] == 151
    assert block_analysis[0]["planned_target_max"] == 155
    assert block_analysis[1]["planned_target_min"] == 300
    assert block_analysis[1]["planned_target_max"] == 310


def test_custom_hr_blocks_keep_minor_upper_deviation_contextual():
    steps = [
        _make_step(1, target_type="hr", target_hr_min=126, target_hr_max=140, duration_sec=1200),
        _make_step(2, target_type="hr", target_hr_min=135, target_hr_max=148, duration_sec=3000),
        _make_step(3, target_type="hr", target_hr_min=135, target_hr_max=150, duration_sec=1200),
    ]
    laps = [
        _make_lap(1, duration_sec=1200, distance_m=3500, avg_hr=140, avg_pace_sec_km=343),
        _make_lap(2, duration_sec=3000, distance_m=9000, avg_hr=148, avg_pace_sec_km=333),
        _make_lap(3, duration_sec=1200, distance_m=3500, avg_hr=151, avg_pace_sec_km=343),
        _make_lap(4, duration_sec=15, distance_m=20, avg_hr=145, avg_pace_sec_km=None),
    ]
    context = _make_context(steps, laps)
    context.planned_session.session_date = date(2026, 5, 16)
    context.activity.local_date = date(2026, 5, 17)
    context.planned_session.expected_duration_min = 90
    context.activity.duration_sec = 5415

    metrics = compute_session_metrics(context)
    # Use the reported drift value from the real scenario to validate the narrative branch.
    metrics["heart_rate"]["cardiac_drift_ratio"] = 0.093
    metrics["derived_flags"]["cardiac_drift_flag"] = True
    metrics["derived_flags"]["cardiac_drift_severity"] = "relevant"
    narrative = _build_fallback_output(context, metrics)

    blocks = metrics["block_analysis"]
    assert blocks[0]["status_detail"] == "within_range_upper_edge"
    assert blocks[1]["status_detail"] == "within_range_upper_edge"
    assert blocks[2]["status_detail"] == "slightly_above_range"
    assert blocks[2]["delta_to_upper"] == 1.0
    assert blocks[2]["short_note"] == "apenas por encima del objetivo"
    assert metrics["derived_flags"]["minor_hr_upper_deviation_only_flag"] is True
    assert metrics["derived_flags"]["work_block_over_target_flag"] is False
    assert metrics["planned_vs_actual"]["planned_date"] == "2026-05-16"
    assert metrics["planned_vs_actual"]["executed_date"] == "2026-05-17"
    assert metrics["planned_vs_actual"]["days_offset"] == 1
    assert metrics["planned_vs_actual"]["executed_on_different_day"] is True
    assert metrics["laps"]["has_only_residual_extra_laps"] is True
    assert metrics["laps"]["effective_extra_laps"] == 0
    assert "intensidad global quedo controlada" in " ".join(narrative.key_positive_points).lower()
    assert "deriva cardiaca relevante" in " ".join(narrative.key_risk_points).lower()
    assert "recuperacion" in narrative.next_recommendation.lower()
    assert "Los bloques de trabajo quedaron por encima" not in narrative.key_risk_points


def test_indoor_cycling_distance_zero_does_not_penalize_compliance():
    steps = [_make_step(1, target_type="hr", target_hr_zone="z2", duration_sec=3000)]
    laps = [_make_lap(1, duration_sec=3000, distance_m=0, avg_hr=140, avg_pace_sec_km=None)]
    context = _make_context(steps, laps)
    context.planned_session.sport_type = "cycling"
    context.planned_session.expected_distance_km = 25.0
    context.activity.sport_type = "cycling"
    context.activity.distance_m = 0.0
    _set_modality(context, "indoor", "indoor")

    metrics = compute_session_metrics(context)

    assert metrics["compliance"]["distance_score"] is None
    assert metrics["compliance"]["elevation_score"] is None
    assert "Distancia no evaluada por modalidad indoor." in metrics["compliance"]["notes"]
    assert metrics["scores"]["compliance_score"] is not None
    assert metrics["scores"]["compliance_score"] >= 80


def test_indoor_running_distance_zero_uses_low_weight():
    steps = [_make_step(1, target_type="hr", target_hr_zone="z2", duration_sec=3600)]
    laps = [_make_lap(1, duration_sec=3600, distance_m=0, avg_hr=145, avg_pace_sec_km=None)]
    context = _make_context(steps, laps)
    context.activity.distance_m = 0.0
    _set_modality(context, "indoor", "indoor")

    metrics = compute_session_metrics(context)

    assert metrics["compliance"]["distance_score"] is None
    assert "Distancia de cinta tomada como referencia, no como metrica principal." in metrics["compliance"]["notes"]
    assert metrics["scores"]["compliance_score"] is not None
    assert metrics["scores"]["compliance_score"] >= 70


def test_sessions_without_modality_keep_distance_behavior():
    steps = [_make_step(1, target_type="pace", target_pace_zone="z2", duration_sec=3600)]
    laps = [_make_lap(1, duration_sec=3600, distance_m=5000, avg_hr=145, avg_pace_sec_km=430)]
    context = _make_context(steps, laps)
    context.planned_session.expected_distance_km = 10.0
    context.activity.distance_m = 5000.0

    metrics = compute_session_metrics(context)

    assert metrics["compliance"]["distance_score"] == 50.0


def test_indoor_running_with_planned_incline_adds_analysis_note():
    steps = [_make_step(1, target_type="hr", target_hr_zone="z2", duration_sec=3600, incline_pct=8.0)]
    laps = [_make_lap(1, duration_sec=3600, distance_m=7000, avg_hr=145, avg_pace_sec_km=430)]
    context = _make_context(steps, laps)
    context.activity.distance_m = 7000.0
    context.activity.avg_pace_sec_km = 430
    _set_modality(context, "indoor", "indoor")

    metrics = compute_session_metrics(context)

    assert "Sesion en cinta con inclinacion planificada: se prioriza duracion e intensidad sobre ritmo/distancia." in metrics["compliance"]["notes"]
    assert metrics["scores"]["compliance_score"] is not None


def test_short_hr_recovery_uses_prudent_logic_when_execution_was_soft():
    steps = [
        _make_step(1, target_type="pace", target_pace_min=260, target_pace_max=290, duration_sec=60),
        _make_step(2, step_type="recovery", target_type="hr", target_hr_min=120, target_hr_max=140, duration_sec=60),
    ]
    laps = [
        _make_lap(1, duration_sec=60, distance_m=320, avg_hr=160, avg_pace_sec_km=245, avg_cadence=178),
        _make_lap(2, duration_sec=60, distance_m=70, avg_hr=149, avg_pace_sec_km=700, avg_cadence=118),
    ]
    context = _make_context(steps, laps)

    metrics = compute_session_metrics(context)

    recovery = metrics["block_analysis"][1]
    assert recovery["status_detail"] == "executed_soft_but_hr_lagged"
    assert recovery["recovery_effective"] is True
    assert recovery["short_note"] == "recuperacion suave, FC promedio alta por demora fisiologica"
    assert metrics["derived_flags"]["recovery_block_not_effective_flag"] is False
    assert metrics["derived_flags"]["short_recovery_hr_lag_flag"] is True


def test_time_based_session_marks_distance_as_informational():
    steps = [
        _make_step(1, target_type="hr", target_hr_min=126, target_hr_max=145, duration_sec=2400),
        _make_step(2, repeat_count=4, target_type="pace", target_pace_min=260, target_pace_max=290, duration_sec=60),
        _make_step(3, repeat_count=4, step_type="recovery", target_type="hr", target_hr_min=120, target_hr_max=140, duration_sec=60),
        _make_step(4, target_type="hr", target_hr_min=120, target_hr_max=140, duration_sec=300),
    ]
    laps = [
        _make_lap(1, duration_sec=2400, distance_m=6500, avg_hr=146, avg_pace_sec_km=369),
        _make_lap(2, duration_sec=60, distance_m=280, avg_hr=160, avg_pace_sec_km=240),
        _make_lap(3, duration_sec=60, distance_m=80, avg_hr=145, avg_pace_sec_km=700),
        _make_lap(4, duration_sec=60, distance_m=282, avg_hr=161, avg_pace_sec_km=238),
        _make_lap(5, duration_sec=60, distance_m=82, avg_hr=144, avg_pace_sec_km=705),
        _make_lap(6, duration_sec=60, distance_m=285, avg_hr=162, avg_pace_sec_km=236),
        _make_lap(7, duration_sec=60, distance_m=78, avg_hr=143, avg_pace_sec_km=710),
        _make_lap(8, duration_sec=60, distance_m=284, avg_hr=163, avg_pace_sec_km=235),
        _make_lap(9, duration_sec=60, distance_m=80, avg_hr=142, avg_pace_sec_km=715),
        _make_lap(10, duration_sec=327, distance_m=900, avg_hr=138, avg_pace_sec_km=363),
    ]
    context = _make_context(steps, laps)
    context.planned_session.expected_distance_km = None
    context.activity.duration_sec = 3267
    context.activity.distance_m = 9470

    metrics = compute_session_metrics(context)

    assert metrics["session_target_basis"] == "duration"
    assert metrics["distance_is_informational"] is True
    assert metrics["compliance"]["distance_score"] is None
    assert metrics["derived_flags"]["distance_informational_flag"] is True
    assert metrics["derived_flags"]["distance_over_target_flag"] is False


def test_duration_within_tolerance_does_not_raise_strong_flag():
    steps = [_make_step(1, target_type="hr", target_hr_min=126, target_hr_max=145, duration_sec=3180)]
    laps = [_make_lap(1, duration_sec=3269, distance_m=9000, avg_hr=140, avg_pace_sec_km=363)]
    context = _make_context(steps, laps)
    context.planned_session.expected_duration_min = 53
    context.activity.duration_sec = 3269

    metrics = compute_session_metrics(context)

    assert round(metrics["planned_vs_actual"]["duration"]["delta_pct"], 1) == 2.8
    assert metrics["derived_flags"]["duration_within_tolerance_flag"] is True
    assert metrics["derived_flags"]["duration_over_target_flag"] is False


def test_technical_stride_is_detected_and_softened():
    steps = [_make_step(1, target_type="pace", target_pace_min=260, target_pace_max=290, duration_sec=60)]
    laps = [_make_lap(1, duration_sec=60, distance_m=300, avg_hr=160, avg_pace_sec_km=240)]
    context = _make_context(steps, laps)
    context.planned_session.title = "Aerobico con tecnica"
    context.planned_session.session_type = "aerobic"

    metrics = compute_session_metrics(context)

    block = metrics["block_analysis"][0]
    assert block["block_subtype"] in {"technical_stride", "progressive_technical"}
    assert block["status_detail"] == "faster_than_target"
    assert block["short_note"] == "progresivo algo intenso"
    assert metrics["derived_flags"]["technical_stride_intensity_flag"] is True
    assert metrics["derived_flags"]["work_block_over_target_flag"] is False


def test_pace_direction_labels_are_explicit():
    steps = [
        _make_step(1, target_type="pace", target_pace_min=260, target_pace_max=290, distance_m=1000),
        _make_step(2, target_type="pace", target_pace_min=260, target_pace_max=290, distance_m=1000),
    ]
    laps = [
        _make_lap(1, duration_sec=240, distance_m=1000, avg_hr=160, avg_pace_sec_km=240),
        _make_lap(2, duration_sec=310, distance_m=1000, avg_hr=150, avg_pace_sec_km=310),
    ]
    context = _make_context(steps, laps)

    metrics = compute_session_metrics(context)

    assert metrics["block_analysis"][0]["status_detail"] == "faster_than_target"
    assert metrics["block_analysis"][0]["intensity_interpretation"] == "mas exigente"
    assert metrics["block_analysis"][1]["status_detail"] == "slower_than_target"
    assert metrics["block_analysis"][1]["intensity_interpretation"] == "por debajo del objetivo"


def test_fatigue_evidence_requires_objective_support():
    steps = [_make_step(1, target_type="hr", target_hr_min=126, target_hr_max=145, duration_sec=2400)]
    laps = [_make_lap(1, duration_sec=2400, distance_m=6500, avg_hr=146, avg_pace_sec_km=369)]
    context = _make_context(steps, laps)

    metrics = compute_session_metrics(context)
    narrative = _build_fallback_output(context, metrics)

    assert metrics["derived_flags"]["fatigue_evidence_level"] == "none"
    assert metrics["derived_flags"]["fatigue_evidence_reasons"] == []
    assert "fatiga previa evidente" not in narrative.analysis_natural.lower()


def test_fatigue_evidence_supported_when_health_markers_are_low():
    steps = [_make_step(1, target_type="hr", target_hr_min=126, target_hr_max=145, duration_sec=2400)]
    laps = [_make_lap(1, duration_sec=2400, distance_m=6500, avg_hr=146, avg_pace_sec_km=369)]
    context = _make_context(steps, laps)
    context.health = type(
        "HealthStub",
        (),
        {
            "sleep_hours": 5.4,
            "sleep_score": 58,
            "hrv_status": "low",
            "stress_avg": 46,
            "body_battery_start": 30,
            "recovery_time_hours": 26.0,
        },
    )()

    metrics = compute_session_metrics(context)

    assert metrics["derived_flags"]["fatigue_evidence_level"] in {"supported", "strong"}
    assert metrics["derived_flags"]["fatigue_evidence_reasons"]
