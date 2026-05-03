from __future__ import annotations

from datetime import date

from app.services.analysis_v2.metrics import compute_session_metrics
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
        target_notes=None,
    )


def _make_lap(index: int, *, duration_sec: int, distance_m: float, avg_hr: int | None, avg_pace_sec_km: float | None) -> ActivityLapContext:
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
        max_hr=None,
        avg_pace_sec_km=avg_pace_sec_km,
        avg_power=None,
        max_power=None,
        avg_cadence=None,
        max_cadence=None,
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
            session_type=None,
            description=None,
            target_notes=None,
            planned_start_time=None,
            expected_duration_min=60,
            expected_distance_km=10.0,
            expected_elevation_gain_m=None,
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
    assert any("recuperacion" in note for note in block_notes if note)


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
