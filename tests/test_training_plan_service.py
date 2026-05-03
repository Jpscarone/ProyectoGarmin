from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import goal  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.schemas.training_plan import PlanGoalInput, TrainingPlanCreate, TrainingPlanUpdate
from app.services.training_plan_service import (
    auto_complete_expired_training_plans,
    create_training_plan,
    get_training_plan_detail,
    select_default_training_plan,
    update_training_plan,
)


class TrainingPlanServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete_row = Athlete(name="Atleta Plan")
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_create_training_plan_with_primary_and_secondary_goals(self) -> None:
        created = create_training_plan(
            self.db,
            TrainingPlanCreate(
                athlete_id=self.athlete.id,
                name="Plan Maraton",
                sport_type="running",
                start_date=date(2026, 3, 1),
                end_date=date(2026, 5, 1),
                status="active",
                primary_goal=PlanGoalInput(
                    name="Objetivo A",
                    sport_type="running",
                    event_date=date(2026, 4, 20),
                    distance_km=21.1,
                ),
                secondary_goals=[
                    PlanGoalInput(name="Test 10k", sport_type="running", event_date=date(2026, 3, 30), distance_km=10),
                    PlanGoalInput(name="Carrera B", sport_type="running", event_date=date(2026, 4, 10), distance_km=15),
                ],
            ),
        )

        plan = get_training_plan_detail(self.db, created.id)
        self.assertIsNotNone(plan.goal)
        self.assertEqual(plan.goal.goal_role, "primary")
        self.assertEqual(len(plan.goals), 3)
        self.assertEqual(len([goal for goal in plan.goals if goal.goal_role == "secondary"]), 2)

    def test_update_training_plan_replaces_secondary_goals_and_keeps_primary(self) -> None:
        created = create_training_plan(
            self.db,
            TrainingPlanCreate(
                athlete_id=self.athlete.id,
                name="Plan Trail",
                sport_type="trail_running",
                primary_goal=PlanGoalInput(name="Trail A", sport_type="trail_running", event_date=date(2026, 6, 1)),
                secondary_goals=[PlanGoalInput(name="Vertical", sport_type="trail_running", event_date=date(2026, 5, 10))],
            ),
        )

        updated = update_training_plan(
            self.db,
            created,
            TrainingPlanUpdate(
                secondary_goals=[PlanGoalInput(name="Tirada control", sport_type="trail_running", event_date=date(2026, 5, 20))],
                primary_goal=PlanGoalInput(
                    id=created.goal_id,
                    name="Trail A principal",
                    sport_type="trail_running",
                    event_date=date(2026, 6, 1),
                ),
            ),
        )

        plan = get_training_plan_detail(self.db, updated.id)
        self.assertEqual(plan.goal.name, "Trail A principal")
        secondary_goals = [goal for goal in plan.goals if goal.goal_role == "secondary"]
        self.assertEqual(len(secondary_goals), 1)
        self.assertEqual(secondary_goals[0].name, "Tirada control")

    def test_auto_complete_expired_active_training_plans(self) -> None:
        expired = create_training_plan(
            self.db,
            TrainingPlanCreate(
                athlete_id=self.athlete.id,
                name="Plan vencido",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 1),
                status="active",
            ),
        )
        current = create_training_plan(
            self.db,
            TrainingPlanCreate(
                athlete_id=self.athlete.id,
                name="Plan vigente",
                start_date=date(2026, 4, 1),
                end_date=date(2026, 5, 1),
                status="active",
            ),
        )

        changed = auto_complete_expired_training_plans(self.db, date(2026, 4, 1))

        self.assertEqual(changed, 1)
        self.db.refresh(expired)
        self.db.refresh(current)
        self.assertEqual(expired.status, "completed")
        self.assertEqual(current.status, "active")

    def test_select_default_training_plan_prefers_current_active_plan(self) -> None:
        old_plan = create_training_plan(
            self.db,
            TrainingPlanCreate(
                athlete_id=self.athlete.id,
                name="Plan anterior",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 2, 1),
                status="completed",
            ),
        )
        active_plan = create_training_plan(
            self.db,
            TrainingPlanCreate(
                athlete_id=self.athlete.id,
                name="Plan actual",
                start_date=date(2026, 4, 1),
                end_date=date(2026, 5, 1),
                status="active",
            ),
        )

        selected = select_default_training_plan(self.db, athlete_id=self.athlete.id, today=date(2026, 4, 15))

        self.assertEqual(selected.id, active_plan.id)
        self.assertNotEqual(selected.id, old_plan.id)


if __name__ == "__main__":
    unittest.main()
