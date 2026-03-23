from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.activity_matching_service import _activity_local_date, match_activity_to_plan


class ActivityMatchingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete_row = Athlete(name="Atleta Matching")
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

        training_plan_row = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Matching",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 4, 1),
            status="active",
        )
        self.db.add(training_plan_row)
        self.db.commit()
        self.db.refresh(training_plan_row)
        self.training_plan = training_plan_row

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_match_uses_sport_family_compatibility(self) -> None:
        training_day = TrainingDay(
            training_plan_id=self.training_plan.id,
            athlete_id=self.athlete.id,
            day_date=date(2026, 3, 22),
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)

        planned_session_row = PlannedSession(
            training_day_id=training_day.id,
            athlete_id=self.athlete.id,
            sport_type="running",
            discipline_variant="road_running",
            name="Rodaje",
            session_order=1,
            expected_duration_min=50,
        )
        self.db.add(planned_session_row)
        self.db.commit()
        self.db.refresh(planned_session_row)

        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=1001,
            activity_name="Trail",
            sport_type="trail_running",
            start_time=datetime(2026, 3, 22, 8, 0, tzinfo=timezone.utc),
            duration_sec=3000,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        result = match_activity_to_plan(self.db, activity.id)

        self.assertTrue(result.matched)
        self.assertEqual(result.planned_session_id, planned_session_row.id)

    def test_rematch_replaces_previous_link_with_better_candidate(self) -> None:
        training_day = TrainingDay(
            training_plan_id=self.training_plan.id,
            athlete_id=self.athlete.id,
            day_date=date(2026, 3, 22),
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)

        early_session = PlannedSession(
            training_day_id=training_day.id,
            athlete_id=self.athlete.id,
            sport_type="cycling",
            name="Bici suave",
            session_order=1,
            planned_start_time=time(7, 0),
            expected_duration_min=60,
        )
        late_session = PlannedSession(
            training_day_id=training_day.id,
            athlete_id=self.athlete.id,
            sport_type="cycling",
            name="Bici tempo",
            session_order=2,
            planned_start_time=time(18, 0),
            expected_duration_min=90,
        )
        self.db.add_all([early_session, late_session])
        self.db.commit()
        self.db.refresh(early_session)
        self.db.refresh(late_session)

        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=1002,
            activity_name="Salida PM",
            sport_type="road_cycling",
            start_time=datetime(2026, 3, 22, 18, 10),
            duration_sec=5400,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        first_result = match_activity_to_plan(self.db, activity.id)
        self.assertTrue(first_result.matched)
        self.assertEqual(first_result.planned_session_id, late_session.id)

        early_session.planned_start_time = time(18, 5)
        early_session.expected_duration_min = 90
        late_session.planned_start_time = time(20, 0)
        self.db.add(early_session)
        self.db.add(late_session)
        self.db.commit()

        second_result = match_activity_to_plan(self.db, activity.id)
        self.assertTrue(second_result.matched)
        self.assertEqual(second_result.planned_session_id, early_session.id)

    def test_activity_local_date_uses_timezone_when_present(self) -> None:
        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=1003,
            start_time=datetime(2026, 3, 22, 2, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(_activity_local_date(activity), activity.start_time.astimezone().date())


if __name__ == "__main__":
    unittest.main()
