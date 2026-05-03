from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.services.analysis_v2.weekly_narrative import (
    build_weekly_contextual_factors,
    build_weekly_health_context_summary,
    build_weekly_llm_payload,
    _build_weekly_fallback_output,
)


def test_weekly_intensity_imbalance_flag_prioritized() -> None:
    metrics = {
        "derived_flags": {"intensity_distribution_imbalance_flag": True},
        "scores": {"load_score": 40, "consistency_score": 60, "fatigue_score": 70, "balance_score": 50},
        "totals": {"activity_count": 3, "total_duration_sec": 7200},
        "compliance": {"compliance_ratio_pct": 60},
        "trends": {},
        "distribution": {},
    }
    context = type("Context", (), {"athlete": type("Athlete", (), {"primary_sport": "running"})()})()
    output = _build_weekly_fallback_output(context, metrics)
    assert output.risks and "intensidad" in output.risks[0]
    assert output.dominant_week_issue == "intensity_distribution_imbalance"
    assert "intensidad" in output.next_week_recommendation.lower()


def test_weekly_recommendation_prioritizes_fatigue() -> None:
    metrics = {
        "derived_flags": {"high_fatigue_risk_flag": True, "low_consistency_flag": True},
        "scores": {"load_score": 55, "consistency_score": 55, "fatigue_score": 82, "balance_score": 50},
        "totals": {"activity_count": 4, "total_duration_sec": 9000},
        "compliance": {"compliance_ratio_pct": 70},
        "trends": {},
        "distribution": {},
    }
    context = type("Context", (), {"athlete": type("Athlete", (), {"primary_sport": "running"})()})()
    output = _build_weekly_fallback_output(context, metrics)
    assert output.dominant_week_issue == "high_fatigue_risk"
    assert "descarga" in output.next_week_recommendation.lower()


def test_weekly_recommendation_defaults_when_no_flags() -> None:
    metrics = {
        "derived_flags": {},
        "scores": {"load_score": 55, "consistency_score": 72, "fatigue_score": 50, "balance_score": 70},
        "totals": {"activity_count": 4, "total_duration_sec": 9000},
        "compliance": {"compliance_ratio_pct": 80},
        "trends": {},
        "distribution": {},
    }
    context = type("Context", (), {"athlete": type("Athlete", (), {"primary_sport": "running"})()})()
    output = _build_weekly_fallback_output(context, metrics)
    assert output.dominant_week_issue is None
    assert "linea" in output.next_week_recommendation.lower() or "progresion" in output.next_week_recommendation.lower()


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
