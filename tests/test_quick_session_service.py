from __future__ import annotations

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
from app.db.models.session_group import SessionGroup
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.planning.quick_session_service import (
    SessionAdvancedData,
    create_quick_session,
    create_session_from_quick_mode,
)
from app.services.session_group_service import create_inline_group


class QuickSessionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete = Athlete(name="Atleta Test")
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
            day_date=date(2026, 3, 17),
        )
        self.db.add(day)
        self.db.commit()
        self.db.refresh(day)

        self.training_day = day

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_quick_session_generates_one_structured_step(self) -> None:
        result = create_quick_session(
            self.db,
            training_day_id=self.training_day.id,
            sport_type="running",
            discipline_variant="street",
            name="45min suave",
            description_text=None,
            expected_duration_min=45,
            expected_distance_km=None,
            target_hr_zone=None,
            target_power_zone=None,
            target_notes="suave",
            is_key_session=False,
        )

        self.assertEqual(result.created_steps, 1)
        self.assertEqual(len(result.planned_session.planned_session_steps), 1)
        step = result.planned_session.planned_session_steps[0]
        self.assertEqual(step.duration_sec, 2700)
        self.assertEqual(step.target_notes, "suave")

    def test_unified_text_mode_persists_advanced_metadata(self) -> None:
        result = create_session_from_quick_mode(
            self.db,
            training_day_id=self.training_day.id,
            mode="text",
            raw_text="Running + 10min suave + 5x(2min fuerte + 2min suave) + 10min suave",
            advanced_data=SessionAdvancedData(
                name="Martes de calidad",
                session_order=3,
                target_notes="controlado",
                expected_elevation_gain_m=120,
            ),
            is_key_session=True,
        )

        self.assertEqual(result.planned_session.name, "Martes de calidad")
        self.assertEqual(result.planned_session.session_order, 3)
        self.assertEqual(result.planned_session.expected_elevation_gain_m, 120)
        self.assertIn("suave", result.planned_session.target_notes or "")
        self.assertTrue(result.planned_session.is_key_session)
        self.assertGreaterEqual(result.created_steps, 3)

    def test_unified_builder_mode_creates_structured_steps(self) -> None:
        result = create_session_from_quick_mode(
            self.db,
            training_day_id=self.training_day.id,
            mode="builder",
            sport_type="running",
            raw_text="Running + 15min suave + 4x(1500m fuerte + 1:30 suave) + 10min enfriar",
            advanced_data=SessionAdvancedData(session_type="intervals"),
        )

        self.assertEqual(result.planned_session.sport_type, "running")
        self.assertEqual(result.planned_session.session_type, "intervals")
        self.assertEqual(len(result.planned_session.planned_session_steps), 4)

    def test_unified_simple_mode_uses_advanced_fallbacks_without_breaking_step(self) -> None:
        result = create_session_from_quick_mode(
            self.db,
            training_day_id=self.training_day.id,
            mode="simple",
            name="Rodaje regenerativo",
            expected_duration_min=45,
            target_notes="suave",
            advanced_data=SessionAdvancedData(
                sport_type="running",
                session_type="easy",
                planned_start_time=None,
            ),
        )

        self.assertEqual(result.planned_session.sport_type, "running")
        self.assertEqual(result.planned_session.session_type, "easy")
        self.assertEqual(len(result.planned_session.planned_session_steps), 1)
        self.assertEqual(result.planned_session.planned_session_steps[0].duration_sec, 2700)

    def test_session_can_be_created_without_group(self) -> None:
        result = create_session_from_quick_mode(
            self.db,
            training_day_id=self.training_day.id,
            mode="simple",
            sport_type="running",
            name="Rodaje libre",
            expected_duration_min=30,
        )

        self.assertIsNone(result.planned_session.session_group_id)

    def test_session_can_be_assigned_to_existing_group(self) -> None:
        group = SessionGroup(
            training_day_id=self.training_day.id,
            name="Brick",
            group_type="brick",
            group_order=1,
        )
        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)

        result = create_session_from_quick_mode(
            self.db,
            training_day_id=self.training_day.id,
            mode="simple",
            sport_type="running",
            name="Trote post bici",
            expected_duration_min=20,
            advanced_data=SessionAdvancedData(session_group_id=group.id),
        )

        self.assertEqual(result.planned_session.session_group_id, group.id)

    def test_inline_group_creation_can_be_used_before_assigning_session(self) -> None:
        group = create_inline_group(
            self.db,
            training_day_id=self.training_day.id,
            name="Pre carrera",
            group_type="pre_race",
            notes="Activacion y rutina corta",
        )

        result = create_session_from_quick_mode(
            self.db,
            training_day_id=self.training_day.id,
            mode="simple",
            sport_type="running",
            name="Activacion 20min",
            expected_duration_min=20,
            advanced_data=SessionAdvancedData(session_group_id=group.id),
        )

        self.assertEqual(group.name, "Pre carrera")
        self.assertEqual(result.planned_session.session_group_id, group.id)


if __name__ == "__main__":
    unittest.main()
