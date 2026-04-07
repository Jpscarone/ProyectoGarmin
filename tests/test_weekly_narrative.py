from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.services.analysis_v2.weekly_narrative import (
    build_weekly_contextual_factors,
    build_weekly_health_context_summary,
    build_weekly_llm_payload,
)


class WeeklyNarrativeContextTests(unittest.TestCase):
    def test_weekly_health_neutral_is_not_included(self) -> None:
        result = build_weekly_health_context_summary(
            SimpleNamespace(),
            {
                "health_context": {
                    "days_with_health": 5,
                    "avg_sleep_hours": 7.4,
                    "avg_sleep_score": 81,
                    "avg_stress": 19,
                    "avg_body_battery_end": 63,
                    "avg_recovery_time_hours": 9.0,
                },
                "scores": {"fatigue_score": 48, "consistency_score": 78},
            },
        )

        self.assertFalse(result["relevant"])
        self.assertIsNone(result["summary"])

    def test_weekly_health_relevant_is_included(self) -> None:
        result = build_weekly_health_context_summary(
            SimpleNamespace(),
            {
                "health_context": {
                    "days_with_health": 4,
                    "avg_sleep_hours": 6.1,
                    "avg_sleep_score": 62,
                    "avg_stress": 37,
                    "avg_body_battery_end": 31,
                    "avg_recovery_time_hours": 26.0,
                },
                "scores": {"fatigue_score": 72, "consistency_score": 64},
            },
        )

        self.assertTrue(result["relevant"])
        self.assertIn("recuperacion", result["summary"])
        self.assertIn("fatiga acumulada", result["summary"])

    def test_weekly_contextual_factors_are_empty_without_relevant_health(self) -> None:
        result = build_weekly_contextual_factors(
            SimpleNamespace(),
            {
                "health_context": {
                    "days_with_health": 0,
                },
                "scores": {},
            },
        )

        self.assertFalse(result["has_relevant_context"])
        self.assertIsNone(result["summary"])

    def test_weekly_payload_uses_contextual_factors_and_not_raw_health_context(self) -> None:
        context = SimpleNamespace(
            athlete=SimpleNamespace(name="Pablo", primary_sport="running", max_hr=190, vo2max=52.0),
            week_start_date=None,
            week_end_date=None,
            activities=[],
            planned_sessions=[],
            previous_weeks=[],
            health_days=[],
            session_analyses=[],
        )
        metrics = {
            "totals": {"activity_count": 4, "total_duration_sec": 18000},
            "distribution": {},
            "compliance": {},
            "trends": {},
            "consistency": {},
            "health_context": {
                "days_with_health": 4,
                "avg_sleep_hours": 6.0,
                "avg_sleep_score": 61,
                "avg_stress": 38,
                "avg_body_battery_end": 33,
                "avg_recovery_time_hours": 25.0,
            },
            "session_analysis_aggregate": {},
            "derived_flags": {},
            "scores": {"fatigue_score": 73, "consistency_score": 66},
            "rule_thresholds": {},
        }

        payload = build_weekly_llm_payload(context, metrics)

        self.assertIn("contextual_factors", payload)
        self.assertTrue(payload["contextual_factors"]["has_relevant_context"])
        self.assertNotIn("health_context", payload["metrics"])


if __name__ == "__main__":
    unittest.main()
