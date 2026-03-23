from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.planning.presentation import (
    build_session_display_blocks,
    describe_session_structure,
    describe_session_structure_short,
    derive_session_metrics,
    format_duration_human_from_minutes,
    format_duration_human_from_seconds,
)


class PlanningPresentationTests(unittest.TestCase):
    def test_repeat_group_is_kept_as_single_visual_block(self) -> None:
        steps = [
            SimpleNamespace(
                id=1,
                step_order=1,
                step_type="warmup",
                repeat_count=None,
                duration_sec=600,
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
            SimpleNamespace(
                id=2,
                step_order=2,
                step_type="work",
                repeat_count=5,
                duration_sec=120,
                distance_m=None,
                target_hr_min=None,
                target_hr_max=None,
                target_power_min=None,
                target_power_max=None,
                target_pace_min_sec_km=None,
                target_pace_max_sec_km=None,
                target_cadence_min=None,
                target_cadence_max=None,
                target_notes="fuerte",
            ),
            SimpleNamespace(
                id=3,
                step_order=3,
                step_type="steady",
                repeat_count=5,
                duration_sec=120,
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
            SimpleNamespace(
                id=4,
                step_order=4,
                step_type="cooldown",
                repeat_count=None,
                duration_sec=600,
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

        blocks = build_session_display_blocks(steps)

        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0].kind, "simple")
        self.assertEqual(blocks[1].kind, "repeat")
        self.assertEqual(blocks[1].repeat_count, 5)
        self.assertEqual(len(blocks[1].steps), 2)
        self.assertEqual(blocks[1].steps[0].step_type, "work")
        self.assertEqual(blocks[1].steps[1].step_type, "steady")
        self.assertEqual(blocks[2].kind, "simple")

    def test_distance_repeat_group_is_kept_as_single_visual_block(self) -> None:
        steps = [
            SimpleNamespace(
                id=1,
                step_order=1,
                step_type="warmup",
                repeat_count=None,
                duration_sec=900,
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
            SimpleNamespace(
                id=2,
                step_order=2,
                step_type="work",
                repeat_count=4,
                duration_sec=None,
                distance_m=1500,
                target_hr_min=None,
                target_hr_max=None,
                target_power_min=None,
                target_power_max=None,
                target_pace_min_sec_km=None,
                target_pace_max_sec_km=None,
                target_cadence_min=None,
                target_cadence_max=None,
                target_notes="fuerte",
            ),
            SimpleNamespace(
                id=3,
                step_order=3,
                step_type="steady",
                repeat_count=4,
                duration_sec=90,
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
            SimpleNamespace(
                id=4,
                step_order=4,
                step_type="cooldown",
                repeat_count=None,
                duration_sec=600,
                distance_m=None,
                target_hr_min=None,
                target_hr_max=None,
                target_power_min=None,
                target_power_max=None,
                target_pace_min_sec_km=None,
                target_pace_max_sec_km=None,
                target_cadence_min=None,
                target_cadence_max=None,
                target_notes="enfriar",
            ),
        ]

        blocks = build_session_display_blocks(steps)

        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[1].kind, "repeat")
        self.assertEqual(blocks[1].repeat_count, 4)
        self.assertEqual(blocks[1].steps[0].distance_m, 1500)
        self.assertEqual(blocks[1].steps[1].duration_sec, 90)

    def test_duration_formatter_is_human_friendly(self) -> None:
        self.assertEqual(format_duration_human_from_seconds(120), "2min")
        self.assertEqual(format_duration_human_from_seconds(600), "10min")
        self.assertEqual(format_duration_human_from_seconds(30), "30s")
        self.assertEqual(format_duration_human_from_seconds(90), "1:30")
        self.assertEqual(format_duration_human_from_seconds(3600), "1h")
        self.assertEqual(format_duration_human_from_seconds(4500), "1h 15min")
        self.assertEqual(format_duration_human_from_minutes(75), "1h 15min")

    def test_derived_metrics_avoid_incoherent_duration_distance_mix(self) -> None:
        session = SimpleNamespace(
            name="Running intervalos 16 min",
            sport_type="running",
            expected_duration_min=16,
            expected_distance_km=8.0,
            session_type="intervals",
            target_notes="suave",
            planned_session_steps=[
                SimpleNamespace(
                    id=1,
                    step_order=1,
                    step_type="warmup",
                    repeat_count=None,
                    duration_sec=600,
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
                SimpleNamespace(
                    id=2,
                    step_order=2,
                    step_type="work",
                    repeat_count=4,
                    duration_sec=None,
                    distance_m=2000,
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
                    id=3,
                    step_order=3,
                    step_type="steady",
                    repeat_count=4,
                    duration_sec=90,
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
            ],
        )

        metrics = derive_session_metrics(session)

        self.assertIsNone(metrics.duration_sec)
        self.assertEqual(metrics.distance_m, 8000)
        self.assertEqual(metrics.title, "Running 4x2km Z4")

    def test_structure_summary_keeps_top_level_blocks_and_repeat_grouping(self) -> None:
        session = SimpleNamespace(
            expected_duration_min=None,
            expected_distance_km=None,
            target_notes=None,
            session_type="intervals",
            planned_session_steps=[
                SimpleNamespace(
                    id=1,
                    step_order=1,
                    step_type="warmup",
                    repeat_count=None,
                    duration_sec=600,
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
                SimpleNamespace(
                    id=2,
                    step_order=2,
                    step_type="work",
                    repeat_count=5,
                    duration_sec=120,
                    distance_m=None,
                    target_hr_min=None,
                    target_hr_max=None,
                    target_power_min=None,
                    target_power_max=None,
                    target_pace_min_sec_km=None,
                    target_pace_max_sec_km=None,
                    target_cadence_min=None,
                    target_cadence_max=None,
                    target_notes="fuerte",
                ),
                SimpleNamespace(
                    id=3,
                    step_order=3,
                    step_type="steady",
                    repeat_count=5,
                    duration_sec=120,
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
                SimpleNamespace(
                    id=4,
                    step_order=4,
                    step_type="cooldown",
                    repeat_count=None,
                    duration_sec=600,
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
            ],
        )

        summary = describe_session_structure(session)

        self.assertEqual(summary, "10min suave + 5x(2min fuerte + 2min suave) + 10min suave")

    def test_structure_summary_short_is_compact_but_clear(self) -> None:
        session = SimpleNamespace(
            expected_duration_min=None,
            expected_distance_km=None,
            target_notes=None,
            session_type="intervals",
            planned_session_steps=[
                SimpleNamespace(
                    id=1,
                    step_order=1,
                    step_type="warmup",
                    repeat_count=None,
                    duration_sec=600,
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
                SimpleNamespace(
                    id=2,
                    step_order=2,
                    step_type="work",
                    repeat_count=4,
                    duration_sec=None,
                    distance_m=2000,
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
                    id=3,
                    step_order=3,
                    step_type="recovery",
                    repeat_count=4,
                    duration_sec=90,
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
            ],
        )

        summary = describe_session_structure_short(session)

        self.assertEqual(summary, "10min suave + 4x(2km+1:30) Z4")


if __name__ == "__main__":
    unittest.main()
