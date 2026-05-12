from __future__ import annotations

from types import SimpleNamespace

from app.routers.training_plans import _resolve_calendar_day_status


def test_calendar_day_status_uses_linked_activity_when_reports_are_missing() -> None:
    training_day = SimpleNamespace(
        analysis_reports=[],
        planned_sessions=[
            SimpleNamespace(
                analysis_reports=[],
                activity_match=SimpleNamespace(garmin_activity=SimpleNamespace(id=54)),
            )
        ],
    )

    assert _resolve_calendar_day_status(training_day) == ("correct", "Actividad vinculada")


def test_calendar_day_status_uses_manual_strength_completion_when_reports_are_missing() -> None:
    training_day = SimpleNamespace(
        analysis_reports=[],
        planned_sessions=[
            SimpleNamespace(
                sport_type="strength",
                completed_at="2026-05-10T10:00:00Z",
                completion_source="manual",
                analysis_reports=[],
                activity_match=None,
            )
        ],
    )

    assert _resolve_calendar_day_status(training_day) == ("correct", "Completado")
