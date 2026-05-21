from __future__ import annotations

from datetime import date

from app.services.analysis_v2.weekly_analysis_service import (
    WeeklyAthleteContext,
    WeeklyContext,
    WeeklyPlannedSessionContext,
    compute_week_metrics,
)
from app.services.analysis_v2.weekly_narrative import _build_weekly_fallback_output


def _build_context(*planned_sessions: WeeklyPlannedSessionContext) -> WeeklyContext:
    return WeeklyContext(
        athlete=WeeklyAthleteContext(
            id=1,
            name="Pablo",
            primary_sport="running",
            max_hr=190,
            resting_hr=50,
            vo2max=52.0,
        ),
        reference_date=date(2026, 5, 3),
        week_start_date=date(2026, 4, 27),
        week_end_date=date(2026, 5, 3),
        activities=[],
        planned_sessions=list(planned_sessions),
        session_analyses=[],
        health_days=[],
        previous_weeks=[],
    )


def _strength_session(
    *,
    focus: str = "lower_body",
    duration: int = 50,
    rpe: int | None = 6,
    completed: bool = True,
) -> WeeklyPlannedSessionContext:
    return WeeklyPlannedSessionContext(
        planned_session_id=1,
        session_date=date(2026, 4, 29),
        title="Gimnasio pierna",
        sport_type="strength",
        modality=None,
        session_type=None,
        expected_duration_min=duration,
        expected_distance_km=None,
        strength_focus=focus,
        strength_rpe=rpe,
        target_type=None,
        target_hr_zone=None,
        target_pace_zone=None,
        target_power_zone=None,
        target_rpe_zone=None,
        is_key_session=False,
        completed=completed,
        matched=False,
        manual_completed=completed,
        linked_activity_id=None,
        completed_duration_sec=duration * 60 if completed else None,
        completed_strength_focus=focus if completed else None,
        completed_strength_rpe=rpe if completed else None,
        completion_method="manual" if completed else None,
    )


def test_strength_is_included_in_weekly_metrics() -> None:
    metrics = compute_week_metrics(_build_context(_strength_session(duration=50, rpe=6)))

    assert metrics["totals"]["strength_sessions_count"] == 1
    assert metrics["totals"]["strength_total_duration_min"] == 50
    assert metrics["totals"]["strength_load_score"] == 300
    assert metrics["distribution"]["sessions_by_sport"]["counts"]["strength"] == 1


def test_strength_increases_weekly_fatigue_score() -> None:
    without_strength = compute_week_metrics(_build_context())
    with_strength = compute_week_metrics(_build_context(_strength_session()))

    assert (with_strength["scores"]["fatigue_score"] or 0) > (without_strength["scores"]["fatigue_score"] or 0)


def test_pending_strength_does_not_count_as_completed_or_add_load() -> None:
    metrics = compute_week_metrics(_build_context(_strength_session(completed=False)))

    assert metrics["compliance"]["completed_sessions"] == 0
    assert metrics["totals"]["strength_sessions_count"] == 0
    assert metrics["totals"]["strength_total_duration_min"] == 0
    assert metrics["totals"]["total_distance_m"] == 0


def test_weekly_narrative_mentions_strength_and_lower_body() -> None:
    context = _build_context(_strength_session())
    metrics = compute_week_metrics(context)

    output = _build_weekly_fallback_output(context, metrics)

    assert "fuerza" in output.analysis_natural.lower()
    assert "tren inferior" in " ".join(output.main_findings).lower()
