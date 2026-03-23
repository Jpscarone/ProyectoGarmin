from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.analysis.comparator import _build_item_rows
from app.services.analysis.recommendations import build_recommendation_text, build_summary_text
from app.services.analysis.scoring import compare_relative


class AnalysisReportingTests(unittest.TestCase):
    def test_compare_relative_returns_fulfillment_pct(self) -> None:
        result = compare_relative(60, 42)

        self.assertEqual(result["status"], "failed")
        self.assertAlmostEqual(result["fulfillment_pct"], 70.0)

    def test_summary_text_is_more_explanatory(self) -> None:
        summary = build_summary_text(
            "partial",
            ["duracion parcial", "distancia por debajo de lo esperado", "intensidad con datos insuficientes"],
            [],
        )

        self.assertIn("Factores principales", summary)
        self.assertIn("duracion", summary.lower())

    def test_recommendation_text_mentions_partial_review(self) -> None:
        recommendation = build_recommendation_text("partial", [], True)

        self.assertIn("sesion parcial", recommendation.lower())
        self.assertIn("bloques", recommendation.lower())

    def test_repeated_steps_are_expanded_against_laps(self) -> None:
        planned_session = SimpleNamespace(
            planned_session_steps=[
                SimpleNamespace(
                    id=1,
                    step_order=1,
                    step_type="work",
                    repeat_count=3,
                    duration_sec=None,
                    distance_m=1000,
                    target_hr_min=None,
                    target_hr_max=None,
                    target_power_min=None,
                    target_power_max=None,
                    target_pace_min_sec_km=None,
                    target_pace_max_sec_km=None,
                    target_cadence_min=None,
                    target_cadence_max=None,
                    target_notes="Z4",
                ),
                SimpleNamespace(
                    id=2,
                    step_order=2,
                    step_type="recovery",
                    repeat_count=3,
                    duration_sec=30,
                    distance_m=None,
                    target_hr_min=None,
                    target_hr_max=None,
                    target_power_min=None,
                    target_power_max=None,
                    target_pace_min_sec_km=None,
                    target_pace_max_sec_km=None,
                    target_cadence_min=None,
                    target_cadence_max=None,
                    target_notes="suave",
                ),
            ]
        )
        activity = SimpleNamespace(
            laps=[
                SimpleNamespace(lap_number=1, duration_sec=300, distance_m=1000, avg_hr=143, avg_power=None, avg_pace_sec_km=305, avg_cadence=None),
                SimpleNamespace(lap_number=2, duration_sec=30, distance_m=45, avg_hr=140, avg_power=None, avg_pace_sec_km=700, avg_cadence=None),
                SimpleNamespace(lap_number=3, duration_sec=301, distance_m=1000, avg_hr=145, avg_power=None, avg_pace_sec_km=306, avg_cadence=None),
                SimpleNamespace(lap_number=4, duration_sec=30, distance_m=42, avg_hr=141, avg_power=None, avg_pace_sec_km=710, avg_cadence=None),
                SimpleNamespace(lap_number=5, duration_sec=299, distance_m=1000, avg_hr=146, avg_power=None, avg_pace_sec_km=304, avg_cadence=None),
                SimpleNamespace(lap_number=6, duration_sec=30, distance_m=40, avg_hr=139, avg_power=None, avg_pace_sec_km=720, avg_cadence=None),
            ]
        )

        rows = _build_item_rows(planned_session, activity)

        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["planned_value_text"] != "Sin step planificado" for row in rows))
        self.assertEqual(rows[0]["reference_label"], "Step 1 / Lap 1")
        self.assertEqual(rows[1]["reference_label"], "Step 2 / Lap 2")
        self.assertEqual(rows[2]["reference_label"], "Step 3 / Lap 3")
        self.assertEqual(rows[5]["reference_label"], "Step 6 / Lap 6")


if __name__ == "__main__":
    unittest.main()
