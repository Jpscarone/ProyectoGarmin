from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.services.analysis_v2.narrative import (
    build_analysis_context_flags,
    build_health_context_summary,
    build_llm_payload,
    build_relevant_context_for_llm,
    build_weather_context_summary,
)


class AnalysisV2NarrativeContextTests(unittest.TestCase):
    def test_weather_neutral_is_not_included(self) -> None:
        weather = SimpleNamespace(
            apparent_temperature_c=22.0,
            temperature_c=22.0,
            humidity_pct=55.0,
            wind_speed_kmh=10.0,
            precipitation_total_mm=0.0,
            precipitation_mm=0.0,
        )

        result = build_weather_context_summary(weather, {"derived_flags": {}})

        self.assertFalse(result["relevant"])
        self.assertIsNone(result["summary"])

    def test_high_heat_is_included(self) -> None:
        weather = SimpleNamespace(
            apparent_temperature_c=31.0,
            temperature_c=30.0,
            humidity_pct=78.0,
            wind_speed_kmh=12.0,
            precipitation_total_mm=0.0,
            precipitation_mm=0.0,
        )

        result = build_weather_context_summary(weather, {"derived_flags": {"heat_impact_flag": True}})

        self.assertTrue(result["relevant"])
        self.assertIn("temperatura alta", result["summary"])
        self.assertIn("frecuencia cardiaca", result["summary"])

    def test_health_normal_is_not_included(self) -> None:
        health = SimpleNamespace(
            sleep_hours=7.5,
            sleep_score=82,
            hrv_status="balanced",
            stress_avg=18,
            body_battery_start=78,
            recovery_time_hours=8.0,
        )

        result = build_health_context_summary(health, {"scores": {"control_score": 88, "fatigue_score": 40}})

        self.assertFalse(result["relevant"])
        self.assertIsNone(result["summary"])

    def test_clear_fatigue_is_included(self) -> None:
        health = SimpleNamespace(
            sleep_hours=5.3,
            sleep_score=54,
            hrv_status="low",
            stress_avg=46,
            body_battery_start=32,
            recovery_time_hours=28.0,
        )

        result = build_health_context_summary(health, {"scores": {"control_score": 68, "fatigue_score": 72}})

        self.assertTrue(result["relevant"])
        self.assertIn("fatiga", result["summary"])
        self.assertIn("control del esfuerzo", result["summary"])

    def test_weather_and_health_both_relevant_are_combined(self) -> None:
        context = SimpleNamespace(
            weather=SimpleNamespace(
                apparent_temperature_c=32.0,
                temperature_c=31.0,
                humidity_pct=80.0,
                wind_speed_kmh=8.0,
                precipitation_total_mm=0.0,
                precipitation_mm=0.0,
            ),
            health=SimpleNamespace(
                sleep_hours=5.8,
                sleep_score=58,
                hrv_status="unbalanced",
                stress_avg=44,
                body_battery_start=36,
                recovery_time_hours=26.0,
            ),
        )

        flags = build_analysis_context_flags(
            context,
            {
                "derived_flags": {"heat_impact_flag": True},
                "scores": {"control_score": 66, "fatigue_score": 74},
            },
        )

        self.assertTrue(flags["weather_relevant"])
        self.assertTrue(flags["health_relevant"])
        self.assertIsNotNone(flags["combined_summary"])

    def test_no_data_does_not_break_or_add_context(self) -> None:
        context = SimpleNamespace(weather=None, health=None)

        result = build_relevant_context_for_llm(context, {})

        self.assertFalse(result["has_relevant_context"])
        self.assertIsNone(result["summary"])

    def test_payload_uses_only_relevant_context_summary(self) -> None:
        context = SimpleNamespace(
            athlete=SimpleNamespace(
                name="Pablo",
                primary_sport="running",
                max_hr=190,
                resting_hr=50,
                running_threshold_pace_sec_km=None,
                cycling_ftp=None,
                vo2max=None,
            ),
            planned_session=SimpleNamespace(
                session_date=None,
                title="Rodaje",
                sport_type="running",
                discipline_variant=None,
                session_type="base",
                description="Rodaje suave",
                target_notes=None,
                expected_duration_min=60,
                expected_distance_km=10.0,
                expected_elevation_gain_m=None,
                target_type="hr",
                target_hr_zone="Z2",
                target_pace_zone=None,
                target_power_zone=None,
                target_rpe_zone=None,
                goal=None,
                steps=[],
            ),
            activity=SimpleNamespace(
                local_date=None,
                start_time=None,
                title="Actividad",
                sport_type="running",
                discipline_variant=None,
                duration_sec=3600,
                moving_duration_sec=3500,
                distance_m=10000.0,
                elevation_gain_m=40.0,
                avg_hr=150,
                max_hr=168,
                avg_pace_sec_km=360.0,
                avg_power=None,
                avg_cadence=166.0,
                calories=700,
                training_effect_aerobic=3.2,
                training_effect_anaerobic=0.2,
                training_load=95.0,
                avg_temperature_c=30.0,
            ),
            activity_laps=[],
            weather=SimpleNamespace(
                apparent_temperature_c=31.0,
                temperature_c=30.0,
                humidity_pct=78.0,
                wind_speed_kmh=12.0,
                precipitation_total_mm=0.0,
                precipitation_mm=0.0,
            ),
            health=None,
            recent_similar_sessions=[],
            weekly_summary=SimpleNamespace(),
        )
        metrics = {
            "planned_vs_actual": {},
            "laps": {},
            "scores": {"control_score": 80, "fatigue_score": 62},
            "derived_flags": {"heat_impact_flag": True},
            "comparisons": {},
            "weekly_context": {},
            "heart_rate": {},
            "pace": {},
            "power": None,
            "cadence": {},
            "intensity": {},
        }

        payload = build_llm_payload(context, metrics)

        self.assertIn("contextual_factors", payload)
        self.assertTrue(payload["contextual_factors"]["weather_relevant"])
        self.assertNotIn("weather", payload)
        self.assertNotIn("health", payload)


if __name__ == "__main__":
    unittest.main()
