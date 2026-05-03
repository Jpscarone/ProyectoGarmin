from __future__ import annotations

import json
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import goal  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import session_group  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.routers.planned_sessions import _update_session_from_quick_mode
from app.services.planning.quick_session_service import SessionAdvancedData, create_session_from_quick_mode


class QuickSessionEditingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete = Athlete(
            name="Atleta Test",
            hr_zones_json=json.dumps({"general": [{"name": "Z2", "min": 126, "max": 145}]}, ensure_ascii=True),
            pace_zones_json=json.dumps({"general": [{"name": "Z2", "min": 300, "max": 330}]}, ensure_ascii=True),
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
            day_date=date(2026, 5, 2),
        )
        self.db.add(day)
        self.db.commit()
        self.db.refresh(day)

        self.training_day = day

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_edit_builder_session_updates_custom_hr_block(self) -> None:
        created = create_session_from_quick_mode(
            self.db,
            training_day_id=self.training_day.id,
            mode="builder",
            sport_type="running",
            raw_text="Running + 65min FC Z2",
            advanced_data=SessionAdvancedData(name="Fondo corto"),
        )

        updated = _update_session_from_quick_mode(
            self.db,
            planned_session=created.planned_session,
            training_day_id=self.training_day.id,
            mode="builder",
            sport_type="running",
            raw_text="Running + 65min FC 140-150 bpm",
            builder_blocks_json='[{"kind":"simple","value":"65","unit":"min","targetType":"hr","targetZone":"__custom__","customMin":"140","customMax":"150","stepType":"steady"}]',
            advanced_data=SessionAdvancedData(
                name="Fondo corto",
                expected_duration_min=65,
                expected_distance_km=11.5,
            ),
        )

        step = updated.planned_session.planned_session_steps[0]
        self.assertEqual(updated.planned_session.description_text, "Running + 65min FC 140-150 bpm")
        self.assertEqual(step.target_type, "hr")
        self.assertIsNone(step.target_hr_zone)
        self.assertEqual(step.target_hr_min, 140)
        self.assertEqual(step.target_hr_max, 150)

    def test_edit_text_session_updates_text_and_steps(self) -> None:
        created = create_session_from_quick_mode(
            self.db,
            training_day_id=self.training_day.id,
            mode="text",
            raw_text="Running + 30min suave",
            advanced_data=SessionAdvancedData(name="Texto original"),
        )

        updated = _update_session_from_quick_mode(
            self.db,
            planned_session=created.planned_session,
            training_day_id=self.training_day.id,
            mode="text",
            sport_type="running",
            raw_text="Running + 10min suave + 4x(2min fuerte + 2min suave)",
            advanced_data=SessionAdvancedData(name="Texto editado"),
        )

        self.assertEqual(updated.planned_session.name, "Texto editado")
        self.assertIn("4x", updated.planned_session.description_text or "")
        self.assertGreaterEqual(len(updated.planned_session.planned_session_steps), 3)

    def test_edit_simple_session_updates_summary_fields(self) -> None:
        created = create_session_from_quick_mode(
            self.db,
            training_day_id=self.training_day.id,
            mode="simple",
            sport_type="running",
            name="Rodaje base",
            expected_duration_min=45,
            target_notes="suave",
        )

        updated = _update_session_from_quick_mode(
            self.db,
            planned_session=created.planned_session,
            training_day_id=self.training_day.id,
            mode="simple",
            sport_type="running",
            name="50min controlado",
            expected_duration_min=50,
            target_notes="controlado",
            advanced_data=SessionAdvancedData(name="Rodaje progresivo"),
        )

        self.assertEqual(updated.planned_session.name, "Rodaje progresivo")
        self.assertEqual(updated.planned_session.expected_duration_min, 50)
        self.assertEqual(updated.planned_session.planned_session_steps[0].duration_sec, 3000)


if __name__ == "__main__":
    unittest.main()
