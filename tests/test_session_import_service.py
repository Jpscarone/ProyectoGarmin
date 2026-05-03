from __future__ import annotations

import json
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import session_group  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.session_import_service import create_session_import, preview_session_import


class SessionImportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete = Athlete(
            name="Atleta Test",
            hr_zones_json=json.dumps(
                {"general": [{"name": "Z2", "min": 120, "max": 140}]},
                ensure_ascii=True,
            ),
            pace_zones_json=json.dumps(
                {"general": [{"name": "Z2", "min": 300, "max": 330}]},
                ensure_ascii=True,
            ),
            power_zones_json=json.dumps(
                {"general": [{"name": "Z2", "min": 180, "max": 220}]},
                ensure_ascii=True,
            ),
        )
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)

        plan = TrainingPlan(athlete_id=athlete.id, name="Plan Test")
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)

        day = TrainingDay(
            training_plan_id=plan.id,
            athlete_id=athlete.id,
            day_date=date(2026, 4, 5),
        )
        self.db.add(day)
        self.db.commit()
        self.db.refresh(day)

        self.training_day = day
        self.training_plan = plan

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_preview_uses_pace_estimation(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running
NAME: Fondo progresivo

BLOCK
VALUE: 20
UNIT: min
INTENSITY: pace
ZONE: z2

END"""
        result = preview_session_import(
            self.db,
            training_day_id=self.training_day.id,
            training_plan_id=None,
            base_date_str=None,
            raw_text=raw,
        )
        self.assertTrue(result.ok)
        session = result.preview["sessions"][0]
        self.assertTrue(session["distance_estimated"])
        self.assertEqual(session["distance"], "3.81 km")

    def test_create_import_repeat_persists_repeat_count(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running
NAME: Repetidos

REPEAT
COUNT: 2

BLOCK
VALUE: 5
UNIT: min
INTENSITY: hr
ZONE: z2

END_REPEAT

END"""
        result = create_session_import(
            self.db,
            training_day_id=self.training_day.id,
            training_plan_id=None,
            base_date_str=None,
            raw_text=raw,
        )
        self.assertTrue(result.ok)

        planned_session = self.db.query(PlannedSession).first()
        self.assertIsNotNone(planned_session)
        self.assertEqual(planned_session.expected_duration_min, 10)
        self.assertEqual(len(planned_session.planned_session_steps), 1)
        step = planned_session.planned_session_steps[0]
        self.assertEqual(step.repeat_count, 2)
        self.assertEqual(step.duration_sec, 300)

    def test_create_import_persists_estimated_distance(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running
NAME: Fondo estimado

BLOCK
VALUE: 20
UNIT: min
INTENSITY: pace
ZONE: z2

END"""
        result = create_session_import(
            self.db,
            training_day_id=self.training_day.id,
            training_plan_id=None,
            base_date_str=None,
            raw_text=raw,
        )
        self.assertTrue(result.ok)
        planned_session = self.db.query(PlannedSession).first()
        self.assertEqual(planned_session.expected_distance_km, 3.81)

    def test_power_does_not_estimate_distance(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: cycling
NAME: Bici base

BLOCK
VALUE: 30
UNIT: min
INTENSITY: power
ZONE: z2

END"""
        result = preview_session_import(
            self.db,
            training_day_id=self.training_day.id,
            training_plan_id=None,
            base_date_str=None,
            raw_text=raw,
        )
        self.assertTrue(result.ok)
        session = result.preview["sessions"][0]
        self.assertFalse(session["distance_estimated"])
        self.assertEqual(session["distance"], "-")

    def test_hr_estimation_uses_pace_zones(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running
NAME: Rodaje Z2

BLOCK
VALUE: 15
UNIT: min
INTENSITY: hr
ZONE: z2

END"""
        result = preview_session_import(
            self.db,
            training_day_id=self.training_day.id,
            training_plan_id=None,
            base_date_str=None,
            raw_text=raw,
        )
        self.assertTrue(result.ok)
        session = result.preview["sessions"][0]
        self.assertTrue(session["distance_estimated"])
        self.assertEqual(session["distance"], "2.86 km")

    def test_preview_shows_custom_targets(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running
NAME: Personalizada

BLOCK
VALUE: 10
UNIT: min
INTENSITY: hr
ZONE: custom
HR_MIN: 151
HR_MAX: 155

BLOCK
VALUE: 6
UNIT: min
INTENSITY: pace
ZONE: custom
PACE_MIN: 5:00
PACE_MAX: 5:10

BLOCK
VALUE: 8
UNIT: min
INTENSITY: power
ZONE: custom
POWER_MIN: 280
POWER_MAX: 310

END"""
        result = preview_session_import(
            self.db,
            training_day_id=self.training_day.id,
            training_plan_id=None,
            base_date_str=None,
            raw_text=raw,
        )
        self.assertTrue(result.ok)
        blocks = result.preview["sessions"][0]["blocks"]
        self.assertEqual(blocks[0]["target_label"], "FC personalizada [151-155 bpm]")
        self.assertEqual(blocks[1]["target_label"], "Ritmo personalizado [5:00-5:10 min/km]")
        self.assertEqual(blocks[2]["target_label"], "Potencia personalizada [280-310 W]")
        self.assertEqual(blocks[1]["distance"], "1.18 km")
        self.assertTrue(blocks[1]["distance_estimated"])
        self.assertEqual(blocks[0]["distance"], "-")
        self.assertFalse(blocks[0]["distance_estimated"])

    def test_create_import_persists_custom_targets_like_builder(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running
NAME: Bloques custom

BLOCK
VALUE: 10
UNIT: min
INTENSITY: hr
ZONE: custom
FC_MIN: 151
FC_MAX: 155

BLOCK
VALUE: 6
UNIT: min
INTENSITY: pace
ZONE: custom
PACE_MIN: 5:00
PACE_MAX: 5:10

BLOCK
VALUE: 8
UNIT: min
INTENSITY: power
ZONE: custom
POWER_MIN: 280
POWER_MAX: 310

END"""
        result = create_session_import(
            self.db,
            training_day_id=self.training_day.id,
            training_plan_id=None,
            base_date_str=None,
            raw_text=raw,
        )
        self.assertTrue(result.ok)
        planned_session = self.db.query(PlannedSession).first()
        self.assertIsNotNone(planned_session)
        self.assertAlmostEqual(planned_session.expected_distance_km, 1.18, places=2)
        steps = planned_session.planned_session_steps
        self.assertEqual(len(steps), 3)

        hr_step, pace_step, power_step = steps
        self.assertEqual(hr_step.target_type, "hr")
        self.assertIsNone(hr_step.target_hr_zone)
        self.assertEqual(hr_step.target_hr_min, 151)
        self.assertEqual(hr_step.target_hr_max, 155)

        self.assertEqual(pace_step.target_type, "pace")
        self.assertIsNone(pace_step.target_pace_zone)
        self.assertEqual(pace_step.target_pace_min_sec_km, 300)
        self.assertEqual(pace_step.target_pace_max_sec_km, 310)

        self.assertEqual(power_step.target_type, "power")
        self.assertIsNone(power_step.target_power_zone)
        self.assertEqual(power_step.target_power_min, 280)
        self.assertEqual(power_step.target_power_max, 310)


if __name__ == "__main__":
    unittest.main()
