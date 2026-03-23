from __future__ import annotations

import unittest

from app.services.planning.parser import (
    SessionParseError,
    parse_session_text,
    parse_session_text_to_json,
    parse_standardized_session_text,
)


class PlanningParserTests(unittest.TestCase):
    def test_running_with_repeat_blocks(self) -> None:
        result = parse_session_text("Running + 10min suave + 5x(2min fuerte + 2min suave) + 10min suave")

        self.assertEqual(result.sport_type, "running")
        self.assertEqual(result.session_type, "intervals")
        self.assertEqual(result.expected_duration_min, 40)
        self.assertEqual(len(result.steps), 4)
        self.assertEqual(result.steps[0].step_type, "warmup")
        self.assertEqual(result.steps[1].step_type, "work")
        self.assertEqual(result.steps[1].repeat_count, 5)
        self.assertEqual(result.steps[2].step_type, "steady")
        self.assertEqual(result.steps[2].repeat_count, 5)
        self.assertEqual(result.steps[3].step_type, "cooldown")

    def test_distance_repeat_block(self) -> None:
        result = parse_session_text("15min suave + 4x(1500m fuerte + 1:30 suave) + 10min enfriar")

        self.assertEqual(result.expected_distance_km, 6.0)
        self.assertIsNone(result.expected_duration_min)
        self.assertEqual(result.steps[1].distance_m, 1500)
        self.assertEqual(result.steps[1].repeat_count, 4)
        self.assertEqual(result.steps[2].duration_sec, 90)

    def test_dynamic_title_for_repeat_distance_session(self) -> None:
        result = parse_session_text("Running + 10min suave + 4x(2km Z4 + 90seg suave)")

        self.assertEqual(result.name, "Running 4x(2km Z4 + 1:30 suave)")
        self.assertEqual(result.expected_distance_km, 8.0)
        self.assertIsNone(result.expected_duration_min)

    def test_dynamic_title_for_repeat_time_session(self) -> None:
        result = parse_session_text("Running + 10min suave + 5x(2min fuerte + 2min suave) + 10min suave")

        self.assertEqual(result.name, "Running 5x(2min fuerte + 2min suave)")

    def test_mtb_zone_session(self) -> None:
        structured = parse_standardized_session_text("MTB + 20min Z2 + 3x(8min Z4 + 3min Z1) + 15min Z2")
        as_json = parse_session_text_to_json("MTB + 20min Z2 + 3x(8min Z4 + 3min Z1) + 15min Z2")

        self.assertEqual(structured.sport, "mtb")
        self.assertEqual(len(structured.steps), 3)
        self.assertEqual(as_json["sport"], "mtb")
        self.assertEqual(as_json["steps"][1]["type"], "repeat")
        self.assertEqual(as_json["steps"][1]["repeat_count"], 3)

    def test_simple_duration_session(self) -> None:
        result = parse_session_text("45min suave")

        self.assertEqual(result.expected_duration_min, 45)
        self.assertEqual(result.session_type, "easy")
        self.assertEqual(result.steps, [])

    def test_simple_duration_session_with_real_world_minutes_wording(self) -> None:
        result = parse_session_text("60 minitos suaves")

        self.assertEqual(result.expected_duration_min, 60)
        self.assertEqual(result.session_type, "easy")
        self.assertIn("suave", result.target_notes or "")
        self.assertEqual(result.steps, [])

    def test_simple_bike_base_session(self) -> None:
        result = parse_session_text("1h bici base")

        self.assertEqual(result.expected_duration_min, 60)
        self.assertEqual(result.sport_type, "cycling")
        self.assertEqual(result.session_type, "base")
        self.assertEqual(result.steps, [])

    def test_simple_swimming_distance_session(self) -> None:
        result = parse_session_text("natacion 2000 m continua")

        self.assertEqual(result.expected_distance_km, 2.0)
        self.assertEqual(result.sport_type, "swimming")
        self.assertEqual(result.session_type, "base")
        self.assertEqual(result.steps, [])

    def test_natural_repeat_session_without_parentheses(self) -> None:
        result = parse_session_text("4 x 6 min en Z3 con 3 min suaves")

        self.assertEqual(result.session_type, "intervals")
        self.assertEqual(result.expected_duration_min, 36)
        self.assertEqual(len(result.steps), 2)
        self.assertEqual(result.steps[0].repeat_count, 4)
        self.assertEqual(result.steps[0].step_type, "work")
        self.assertEqual(result.steps[1].repeat_count, 4)
        self.assertEqual(result.steps[1].step_type, "recovery")

    def test_simple_distance_session(self) -> None:
        result = parse_session_text("10km Z2")

        self.assertEqual(result.expected_distance_km, 10.0)
        self.assertEqual(result.target_hr_zone, "Z2")
        self.assertEqual(result.steps, [])

    def test_invalid_empty_repeat(self) -> None:
        with self.assertRaises(SessionParseError):
            parse_standardized_session_text("5x()")

    def test_invalid_incomplete_nested_block(self) -> None:
        with self.assertRaises(SessionParseError):
            parse_standardized_session_text("10min suave + 4x(2min fuerte + ) + 10min suave")

    def test_invalid_repeat_without_parentheses(self) -> None:
        with self.assertRaises(SessionParseError):
            parse_standardized_session_text("10min suave + 4x2min fuerte + 10min suave")

    def test_invalid_unbalanced_parentheses(self) -> None:
        with self.assertRaises(SessionParseError):
            parse_standardized_session_text("10min suave + (2min fuerte + 2min suave")

    def test_invalid_text_without_measurement(self) -> None:
        with self.assertRaises(SessionParseError):
            parse_standardized_session_text("texto cualquiera sin duracion ni distancia")


if __name__ == "__main__":
    unittest.main()
