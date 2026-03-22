from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import session_template  # noqa: F401
from app.db.models import session_template_step  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.session_template_service import create_template_from_planned_session, instantiate_template_for_day


class SessionTemplateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete_row = Athlete(name="Atleta biblioteca")
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

        training_plan_row = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan base",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 4, 1),
            status="active",
        )
        self.db.add(training_plan_row)
        self.db.commit()
        self.db.refresh(training_plan_row)
        self.training_plan = training_plan_row

        self.day_a = TrainingDay(
            training_plan_id=self.training_plan.id,
            athlete_id=self.athlete.id,
            day_date=date(2026, 3, 10),
        )
        self.day_b = TrainingDay(
            training_plan_id=self.training_plan.id,
            athlete_id=self.athlete.id,
            day_date=date(2026, 3, 12),
        )
        self.db.add_all([self.day_a, self.day_b])
        self.db.commit()
        self.db.refresh(self.day_a)
        self.db.refresh(self.day_b)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_create_template_from_existing_session_copies_steps(self) -> None:
        session = PlannedSession(
            training_day_id=self.day_a.id,
            athlete_id=self.athlete.id,
            name="Running 5x2min",
            sport_type="running",
            session_type="intervals",
            expected_duration_min=40,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        self.db.add_all(
            [
                PlannedSessionStep(
                    planned_session_id=session.id,
                    step_order=1,
                    step_type="warmup",
                    duration_sec=600,
                    target_notes="suave",
                ),
                PlannedSessionStep(
                    planned_session_id=session.id,
                    step_order=2,
                    step_type="work",
                    repeat_count=5,
                    duration_sec=120,
                    target_notes="fuerte",
                ),
            ]
        )
        self.db.commit()

        template = create_template_from_planned_session(self.db, planned_session_id=session.id, title="Serie clasica")

        self.assertEqual(template.title, "Serie clasica")
        self.assertEqual(len(template.steps), 2)
        self.assertEqual(template.steps[1].repeat_count, 5)
        self.assertEqual(template.steps[1].target_notes, "fuerte")

    def test_instantiate_template_for_day_creates_independent_session_copy(self) -> None:
        session = PlannedSession(
            training_day_id=self.day_a.id,
            athlete_id=self.athlete.id,
            name="Natacion continua",
            sport_type="swimming",
            session_type="base",
            expected_distance_km=2.0,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        self.db.add(
            PlannedSessionStep(
                planned_session_id=session.id,
                step_order=1,
                step_type="steady",
                distance_m=2000,
                target_notes="continuo",
            )
        )
        self.db.commit()

        template = create_template_from_planned_session(self.db, planned_session_id=session.id, title="Nado continuo 2k")
        copied_session = instantiate_template_for_day(self.db, session_template_id=template.id, training_day_id=self.day_b.id)

        self.assertEqual(copied_session.training_day_id, self.day_b.id)
        self.assertEqual(copied_session.name, "Nado continuo 2k")
        self.assertEqual(len(copied_session.planned_session_steps), 1)
        self.assertEqual(copied_session.planned_session_steps[0].distance_m, 2000)
        self.assertNotEqual(copied_session.id, session.id)


if __name__ == "__main__":
    unittest.main()
