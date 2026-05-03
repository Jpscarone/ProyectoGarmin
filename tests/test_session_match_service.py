from __future__ import annotations

import unittest
from datetime import date, datetime, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import garmin_activity_lap  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.session_match_service import auto_match_activity, manual_match_activity


class SessionMatchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete_row = Athlete(name="Atleta Match")
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

        training_plan_row = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Match",
            sport_type="running",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            status="active",
        )
        self.db.add(training_plan_row)
        self.db.commit()
        self.db.refresh(training_plan_row)
        self.training_plan = training_plan_row

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_clear_same_day_same_sport_match(self) -> None:
        session = self._create_session(date(2026, 4, 6), "Rodaje Z2", "running", time(7, 0), 60, 10.0)
        activity = self._create_activity(date(2026, 4, 6), "Rodaje Garmin", "running", 6, 55, 3540, 9800)

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "matched")
        self.assertEqual(decision.matched_session_id, session.id)
        self.assertGreaterEqual(decision.score or 0, 75.0)

    def test_mismatch_by_sport_is_not_auto_matched(self) -> None:
        self._create_session(date(2026, 4, 6), "Bici base", "cycling", time(7, 0), 90, 40.0)
        activity = self._create_activity(date(2026, 4, 6), "Running Garmin", "running", 6, 55, 3600, 10000)

        decision = auto_match_activity(self.db, activity.id)

        self.assertIn(decision.status, {"unmatched", "candidate"})
        self.assertIsNone(decision.matched_session_id)

    def test_ambiguity_between_two_sessions(self) -> None:
        self._create_session(date(2026, 4, 6), "AM suave", "running", time(7, 0), 60, 10.0)
        self._create_session(date(2026, 4, 6), "PM suave", "running", time(8, 0), 60, 10.0)
        activity = self._create_activity(date(2026, 4, 6), "Rodaje", "running", 7, 30, 3600, 10000)

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "ambiguous")
        self.assertGreaterEqual(len(decision.candidate_sessions), 2)

    def test_match_with_partial_data(self) -> None:
        session = self._create_session(date(2026, 4, 6), "Suave", "running", None, 45, None)
        activity = self._create_activity(date(2026, 4, 6), "Suave reloj", "running", 6, 40, 2700, None)

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "matched")
        self.assertEqual(decision.matched_session_id, session.id)

    def test_auto_match_with_plan_context_does_not_jump_to_other_plan(self) -> None:
        other_plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Otro plan",
            sport_type="running",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            status="active",
        )
        self.db.add(other_plan)
        self.db.commit()
        self.db.refresh(other_plan)

        other_day = TrainingDay(training_plan_id=other_plan.id, athlete_id=self.athlete.id, day_date=date(2026, 4, 6))
        self.db.add(other_day)
        self.db.commit()
        self.db.refresh(other_day)
        other_session = PlannedSession(
            training_day_id=other_day.id,
            athlete_id=self.athlete.id,
            sport_type="running",
            name="Sesion de otro plan",
            session_order=1,
            planned_start_time=time(7, 0),
            expected_duration_min=60,
            expected_distance_km=10.0,
        )
        self.db.add(other_session)
        self.db.commit()
        self.db.refresh(other_session)

        activity = self._create_activity(date(2026, 4, 6), "Rodaje Garmin", "running", 6, 55, 3600, 10000)

        decision = auto_match_activity(self.db, activity.id, training_plan_id=self.training_plan.id)

        self.assertNotEqual(decision.matched_session_id, other_session.id)
        self.assertIn(decision.status, {"unmatched", "candidate"})

    def test_manual_match_overwrites_auto(self) -> None:
        session_a = self._create_session(date(2026, 4, 6), "Rodaje A", "running", time(7, 0), 60, 10.0)
        session_b = self._create_session(date(2026, 4, 6), "Rodaje B", "running", time(18, 0), 60, 10.0)
        activity = self._create_activity(date(2026, 4, 6), "Rodaje", "running", 7, 5, 3600, 10000)

        auto_decision = auto_match_activity(self.db, activity.id)
        self.assertEqual(auto_decision.status, "matched")
        self.assertEqual(auto_decision.matched_session_id, session_a.id)

        manual_decision = manual_match_activity(self.db, activity.id, session_b.id)

        self.assertEqual(manual_decision.status, "matched")
        self.assertEqual(manual_decision.matched_session_id, session_b.id)
        match_row = self.db.scalar(
            self.db.query(ActivitySessionMatch).where(ActivitySessionMatch.garmin_activity_id_fk == activity.id).statement
        )
        self.assertIsNotNone(match_row)
        self.assertEqual(match_row.planned_session_id_fk, session_b.id)
        self.assertEqual(match_row.match_method, "manual")

    def _create_session(
        self,
        session_date: date,
        name: str,
        sport_type: str,
        planned_start_time: time | None,
        expected_duration_min: int | None,
        expected_distance_km: float | None,
    ) -> PlannedSession:
        training_day_row = self.db.query(TrainingDay).filter(
            TrainingDay.training_plan_id == self.training_plan.id,
            TrainingDay.day_date == session_date,
        ).one_or_none()
        if training_day_row is None:
            training_day_row = TrainingDay(
                training_plan_id=self.training_plan.id,
                athlete_id=self.athlete.id,
                day_date=session_date,
            )
            self.db.add(training_day_row)
            self.db.commit()
            self.db.refresh(training_day_row)

        session = PlannedSession(
            training_day_id=training_day_row.id,
            athlete_id=self.athlete.id,
            sport_type=sport_type,
            name=name,
            session_order=1,
            planned_start_time=planned_start_time,
            expected_duration_min=expected_duration_min,
            expected_distance_km=expected_distance_km,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def _create_activity(
        self,
        session_date: date,
        name: str,
        sport_type: str,
        hour: int,
        minute: int,
        duration_sec: int | None,
        distance_m: float | None,
    ) -> GarminActivity:
        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=int(f"{hour}{minute}{len(name)}"),
            activity_name=name,
            sport_type=sport_type,
            start_time=datetime.combine(session_date, time(hour, minute)),
            duration_sec=duration_sec,
            distance_m=distance_m,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)
        return activity


if __name__ == "__main__":
    unittest.main()
