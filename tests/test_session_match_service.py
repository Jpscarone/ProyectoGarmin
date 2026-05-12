from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone

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
from app.db.models.garmin_activity_lap import GarminActivityLap
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.session_match_service import auto_match_activity, manual_match_activity


class SessionMatchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete_row = Athlete(
            name="Atleta Match",
            hr_zones_json='{"general":[{"name":"Z1","min":100,"max":120},{"name":"Z2","min":140,"max":150},{"name":"Z3","min":151,"max":160}]}',
        )
        other_athlete_row = Athlete(name="Otro atleta")
        self.db.add_all([athlete_row, other_athlete_row])
        self.db.commit()
        self.db.refresh(athlete_row)
        self.db.refresh(other_athlete_row)
        self.athlete = athlete_row
        self.other_athlete = other_athlete_row

        training_plan_row = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Match",
            sport_type="running",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            status="active",
        )
        other_plan_row = TrainingPlan(
            athlete_id=self.other_athlete.id,
            name="Plan Otro",
            sport_type="running",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            status="active",
        )
        self.db.add_all([training_plan_row, other_plan_row])
        self.db.commit()
        self.db.refresh(training_plan_row)
        self.db.refresh(other_plan_row)
        self.training_plan = training_plan_row
        self.other_plan = other_plan_row

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_time_based_same_day_running_auto_matches(self) -> None:
        session = self._create_session(
            session_date=date(2026, 4, 6),
            name="Rodaje Z2",
            sport_type="running",
            planned_start_time=time(7, 0),
            expected_duration_min=65,
            expected_distance_km=None,
            steps=[{"step_order": 1, "step_type": "steady", "duration_sec": 3900, "target_type": "hr", "target_hr_min": 140, "target_hr_max": 150}],
        )
        activity = self._create_activity(
            session_date=date(2026, 4, 6),
            name="Rodaje Garmin",
            sport_type="running",
            hour=7,
            minute=10,
            duration_sec=69 * 60,
            distance_m=11300,
            avg_hr=146,
        )

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "matched")
        self.assertEqual(decision.matched_session_id, session.id)
        self.assertGreaterEqual(decision.score or 0, 80.0)
        self.assertEqual(decision.confidence_level, "high")

    def test_trail_running_is_compatible_with_running(self) -> None:
        session = self._create_session(
            session_date=date(2026, 4, 7),
            name="Rodaje trail",
            sport_type="running",
            planned_start_time=time(8, 0),
            expected_duration_min=65,
            expected_distance_km=None,
        )
        activity = self._create_activity(
            session_date=date(2026, 4, 7),
            name="Trail Garmin",
            sport_type="trail_running",
            hour=8,
            minute=5,
            duration_sec=70 * 60,
            distance_m=9000,
            avg_hr=148,
        )

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "matched")
        self.assertEqual(decision.matched_session_id, session.id)
        self.assertIn("deporte compatible", decision.reasons)

    def test_time_based_distance_difference_is_not_penalized_hard(self) -> None:
        session = self._create_session(
            session_date=date(2026, 4, 8),
            name="Base larga",
            sport_type="running",
            planned_start_time=time(7, 30),
            expected_duration_min=60,
            expected_distance_km=10.0,
        )
        activity = self._create_activity(
            session_date=date(2026, 4, 8),
            name="Base reloj",
            sport_type="running",
            hour=7,
            minute=40,
            duration_sec=62 * 60,
            distance_m=7000,
            avg_hr=145,
        )

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "matched")
        self.assertGreaterEqual(decision.score or 0, 80.0)
        self.assertTrue(any("distancia" in item for item in decision.penalties))

    def test_distance_based_distance_difference_penalizes_hard(self) -> None:
        session = self._create_session(
            session_date=date(2026, 4, 9),
            name="10 km Z3",
            sport_type="running",
            planned_start_time=time(7, 0),
            expected_duration_min=None,
            expected_distance_km=10.0,
            steps=[{"step_order": 1, "step_type": "steady", "distance_m": 10000}],
        )
        activity = self._create_activity(
            session_date=date(2026, 4, 9),
            name="Rodaje corto",
            sport_type="running",
            hour=7,
            minute=5,
            duration_sec=48 * 60,
            distance_m=6500,
            avg_hr=150,
        )

        decision = auto_match_activity(self.db, activity.id)

        self.assertIn(decision.status, {"candidate", "unmatched"})
        self.assertLess(decision.score or 100, 80.0)
        self.assertTrue(any("distancia" in item for item in decision.penalties))

    def test_two_similar_candidates_do_not_auto_match(self) -> None:
        self._create_session(date(2026, 4, 10), "AM suave", "running", time(7, 0), 60, None)
        self._create_session(date(2026, 4, 10), "PM suave", "running", time(7, 15), 60, None)
        activity = self._create_activity(
            session_date=date(2026, 4, 10),
            name="Rodaje",
            sport_type="running",
            hour=7,
            minute=10,
            duration_sec=61 * 60,
            distance_m=9800,
            avg_hr=145,
        )

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "ambiguous")
        self.assertIsNone(decision.matched_session_id)
        self.assertIn("candidatos similares", decision.auto_link_decision_reason or "")

    def test_relative_confidence_auto_matches_when_second_candidate_is_far_lower(self) -> None:
        good = self._create_session(date(2026, 4, 11), "Rodaje plan", "running", time(7, 0), 65, None)
        self._create_session(date(2026, 4, 12), "Sesion lejana", "running", time(19, 0), 120, 20.0)
        activity = self._create_activity(
            session_date=date(2026, 4, 11),
            name="Rodaje razonable",
            sport_type="running",
            hour=7,
            minute=20,
            duration_sec=72 * 60,
            distance_m=9500,
            avg_hr=146,
        )

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "matched")
        self.assertEqual(decision.matched_session_id, good.id)
        self.assertGreaterEqual(decision.score or 0, 65.0)
        self.assertEqual(decision.match_method, "same_day_relative_confidence")

    def test_hr_six_bpm_above_range_is_only_light_penalty(self) -> None:
        session = self._create_session(
            session_date=date(2026, 4, 12),
            name="65 min FC 140-150",
            sport_type="running",
            planned_start_time=time(7, 0),
            expected_duration_min=65,
            expected_distance_km=None,
            steps=[{"step_order": 1, "step_type": "steady", "duration_sec": 3900, "target_type": "hr", "target_hr_min": 140, "target_hr_max": 150}],
        )
        activity = self._create_activity(
            session_date=date(2026, 4, 12),
            name="Rodaje arriba",
            sport_type="running",
            hour=7,
            minute=5,
            duration_sec=66 * 60,
            distance_m=10500,
            avg_hr=156,
        )

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "matched")
        self.assertEqual(decision.matched_session_id, session.id)
        self.assertTrue(
            any("FC media compatible con objetivo" in item for item in decision.reasons)
            or any("FC media" in item for item in decision.penalties)
        )

    def test_missing_hr_does_not_fail_or_penalize_too_much(self) -> None:
        session = self._create_session(
            session_date=date(2026, 4, 13),
            name="Base Z2",
            sport_type="running",
            planned_start_time=time(7, 0),
            expected_duration_min=60,
            expected_distance_km=None,
            steps=[{"step_order": 1, "step_type": "steady", "duration_sec": 3600, "target_type": "hr", "target_hr_min": 140, "target_hr_max": 150}],
        )
        activity = self._create_activity(
            session_date=date(2026, 4, 13),
            name="Base sin banda",
            sport_type="running",
            hour=7,
            minute=0,
            duration_sec=61 * 60,
            distance_m=9900,
            avg_hr=None,
        )

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "matched")
        self.assertEqual(decision.matched_session_id, session.id)
        self.assertGreaterEqual(decision.score or 0, 80.0)
        self.assertTrue(any("FC media" in item for item in decision.penalties))

    def test_already_linked_activity_is_not_reconsidered_automatically(self) -> None:
        session = self._create_session(date(2026, 4, 14), "Rodaje A", "running", time(7, 0), 60, None)
        other_session = self._create_session(date(2026, 4, 15), "Rodaje B", "running", time(18, 0), 90, None)
        activity = self._create_activity(
            session_date=date(2026, 4, 14),
            name="Rodaje",
            sport_type="running",
            hour=7,
            minute=5,
            duration_sec=60 * 60,
            distance_m=10000,
            avg_hr=145,
        )

        first = auto_match_activity(self.db, activity.id)
        second = auto_match_activity(self.db, activity.id)

        self.assertEqual(first.matched_session_id, session.id)
        self.assertEqual(second.matched_session_id, session.id)
        self.assertNotEqual(second.matched_session_id, other_session.id)
        self.assertIn("ya estaba vinculada", second.auto_link_decision_reason or "")

    def test_already_linked_session_does_not_receive_second_activity_automatically(self) -> None:
        session = self._create_session(date(2026, 4, 15), "Sesion unica", "running", time(7, 0), 60, None)
        activity_a = self._create_activity(
            session_date=date(2026, 4, 15),
            name="Rodaje A",
            sport_type="running",
            hour=7,
            minute=0,
            duration_sec=60 * 60,
            distance_m=10000,
            avg_hr=145,
        )
        activity_b = self._create_activity(
            session_date=date(2026, 4, 15),
            name="Rodaje B",
            sport_type="running",
            hour=7,
            minute=10,
            duration_sec=61 * 60,
            distance_m=9900,
            avg_hr=146,
        )

        first = auto_match_activity(self.db, activity_a.id)
        second = auto_match_activity(self.db, activity_b.id)

        self.assertEqual(first.status, "matched")
        self.assertIn(second.status, {"candidate", "unmatched"})
        self.assertIsNone(second.matched_session_id)

    def test_manual_match_overwrites_auto(self) -> None:
        session_a = self._create_session(date(2026, 4, 16), "Rodaje A", "running", time(7, 0), 60, None)
        session_b = self._create_session(date(2026, 4, 17), "Rodaje B", "running", time(18, 0), 90, None)
        activity = self._create_activity(
            session_date=date(2026, 4, 16),
            name="Rodaje",
            sport_type="running",
            hour=7,
            minute=5,
            duration_sec=60 * 60,
            distance_m=10000,
            avg_hr=145,
        )

        auto_decision = auto_match_activity(self.db, activity.id)
        manual_decision = manual_match_activity(self.db, activity.id, session_b.id)

        self.assertEqual(auto_decision.status, "matched")
        self.assertEqual(manual_decision.status, "matched")
        self.assertEqual(manual_decision.matched_session_id, session_b.id)
        match_row = self.db.scalar(
            self.db.query(ActivitySessionMatch).where(ActivitySessionMatch.garmin_activity_id_fk == activity.id).statement
        )
        self.assertIsNotNone(match_row)
        self.assertEqual(match_row.planned_session_id_fk, session_b.id)
        self.assertEqual(match_row.match_method, "manual")

    def test_indoor_running_with_incline_lowers_distance_weight(self) -> None:
        session = self._create_session(
            session_date=date(2026, 4, 17),
            name="Cinta subida",
            sport_type="running",
            planned_start_time=time(7, 0),
            expected_duration_min=60,
            expected_distance_km=10.0,
            modality="indoor",
            steps=[{"step_order": 1, "step_type": "steady", "duration_sec": 3600, "target_type": "hr", "target_hr_min": 140, "target_hr_max": 150, "incline_pct": 8.0}],
        )
        activity = self._create_activity(
            session_date=date(2026, 4, 17),
            name="Treadmill Garmin",
            sport_type="running",
            modality="indoor",
            hour=7,
            minute=5,
            duration_sec=61 * 60,
            distance_m=0,
            avg_hr=146,
        )

        decision = auto_match_activity(self.db, activity.id)

        self.assertEqual(decision.status, "matched")
        self.assertEqual(decision.matched_session_id, session.id)
        self.assertGreaterEqual(decision.score or 0, 80.0)

    def _create_session(
        self,
        session_date: date,
        name: str,
        sport_type: str,
        planned_start_time: time | None,
        expected_duration_min: int | None,
        expected_distance_km: float | None,
        *,
        athlete: Athlete | None = None,
        plan: TrainingPlan | None = None,
        steps: list[dict[str, object]] | None = None,
        modality: str | None = None,
    ) -> PlannedSession:
        athlete = athlete or self.athlete
        plan = plan or self.training_plan
        training_day_row = self.db.query(TrainingDay).filter(
            TrainingDay.training_plan_id == plan.id,
            TrainingDay.day_date == session_date,
        ).one_or_none()
        if training_day_row is None:
            training_day_row = TrainingDay(
                training_plan_id=plan.id,
                athlete_id=athlete.id,
                day_date=session_date,
            )
            self.db.add(training_day_row)
            self.db.commit()
            self.db.refresh(training_day_row)

        session = PlannedSession(
            training_day_id=training_day_row.id,
            athlete_id=athlete.id,
            sport_type=sport_type,
            modality=modality,
            name=name,
            session_order=1,
            planned_start_time=planned_start_time,
            expected_duration_min=expected_duration_min,
            expected_distance_km=expected_distance_km,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        for raw_step in steps or []:
            self.db.add(
                PlannedSessionStep(
                    planned_session_id=session.id,
                    step_order=int(raw_step.get("step_order", 1)),
                    step_type=str(raw_step.get("step_type", "steady")),
                    repeat_count=raw_step.get("repeat_count"),
                    duration_sec=raw_step.get("duration_sec"),
                    distance_m=raw_step.get("distance_m"),
                    incline_pct=raw_step.get("incline_pct"),
                    target_type=raw_step.get("target_type"),
                    target_hr_min=raw_step.get("target_hr_min"),
                    target_hr_max=raw_step.get("target_hr_max"),
                    target_hr_zone=raw_step.get("target_hr_zone"),
                )
            )
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
        avg_hr: int | None,
        *,
        athlete: Athlete | None = None,
        laps: list[dict[str, object]] | None = None,
        modality: str | None = None,
    ) -> GarminActivity:
        athlete = athlete or self.athlete
        activity = GarminActivity(
            athlete_id=athlete.id,
            garmin_activity_id=int(f"{hour}{minute}{len(name)}{athlete.id}"),
            activity_name=name,
            sport_type=sport_type,
            modality=modality,
            start_time=datetime.combine(session_date, time(hour, minute), tzinfo=timezone.utc),
            duration_sec=duration_sec,
            distance_m=distance_m,
            avg_hr=avg_hr,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        for index, raw_lap in enumerate(laps or [], start=1):
            self.db.add(
                GarminActivityLap(
                    garmin_activity_id_fk=activity.id,
                    lap_number=index,
                    lap_type=raw_lap.get("lap_type"),
                    duration_sec=raw_lap.get("duration_sec"),
                    distance_m=raw_lap.get("distance_m"),
                    avg_hr=raw_lap.get("avg_hr"),
                )
            )
        self.db.commit()
        self.db.refresh(activity)
        return activity


if __name__ == "__main__":
    unittest.main()
