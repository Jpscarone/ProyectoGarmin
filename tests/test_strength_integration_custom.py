from __future__ import annotations

from datetime import date

from app.services.analysis_v2.weekly_analysis_service import (
    WeeklyAthleteContext,
    WeeklyContext,
    WeeklyPlannedSessionContext,
    WeeklyActivityContext,
    compute_week_metrics,
)


def _build_context(activity: WeeklyActivityContext, planned: WeeklyPlannedSessionContext) -> WeeklyContext:
    return WeeklyContext(
        athlete=WeeklyAthleteContext(id=1, name="A", primary_sport="running", max_hr=190, resting_hr=50, vo2max=50.0),
        reference_date=date(2026, 5, 3),
        week_start_date=date(2026, 4, 27),
        week_end_date=date(2026, 5, 3),
        activities=[activity],
        planned_sessions=[planned],
        session_analyses=[],
        health_days=[],
        previous_weeks=[],
    )


def test_no_double_count_when_garmin_matched_and_manual_completion() -> None:
    # Garmin activity matched to planned session id=10
    activity = WeeklyActivityContext(
        activity_id=100,
        garmin_activity_id=555,
        activity_date=date(2026, 4, 29),
        start_time=None,
        title="Strength Garmin",
        sport_type="strength",
        discipline_variant=None,
        duration_sec=3600,
        distance_m=None,
        elevation_gain_m=None,
        avg_hr=None,
        avg_pace_sec_km=None,
        avg_power=None,
        avg_cadence=None,
        matched_planned_session_id=10,
        planned_session_title="Strength matched",
        session_analysis_id=None,
        session_analysis_summary=None,
        session_compliance_score=None,
        session_execution_score=None,
        session_control_score=None,
        session_fatigue_score=None,
    )

    planned = WeeklyPlannedSessionContext(
        planned_session_id=10,
        session_date=date(2026, 4, 29),
        title="Strength matched",
        sport_type="strength",
        modality=None,
        session_type=None,
        expected_duration_min=60,
        expected_distance_km=None,
        strength_focus="lower_body",
        strength_rpe=6,
        target_type=None,
        target_hr_zone=None,
        target_pace_zone=None,
        target_power_zone=None,
        target_rpe_zone=None,
        is_key_session=False,
        completed=True,
        matched=True,
        manual_completed=True,
        linked_activity_id=555,
        completed_duration_sec=3600,
        completed_strength_focus="lower_body",
        completed_strength_rpe=6,
        completion_method="manual",
    )

    context = _build_context(activity, planned)
    metrics = compute_week_metrics(context)

    # Only one activity must be counted
    assert metrics["totals"]["activity_count"] == 1
    # Strength sessions count comes from planned_sessions and should be 1
    assert metrics["totals"]["strength_sessions_count"] == 1
    # Distribution should report a single strength activity
    assert metrics["distribution"]["sessions_by_sport"]["counts"]["strength"] == 1
    # Total duration should be equal to the activity duration (no double count)
    assert metrics["totals"]["total_duration_sec"] == 3600
