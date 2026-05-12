from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import goal  # noqa: F401
from app.db.models import health_ai_analysis  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import weekly_analysis  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.goal import Goal
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.mcp_context_service import (
    build_last_activity_feedback_payload,
    build_next_session_context_payload,
    build_session_feedback_payload,
    build_week_context_payload,
)


class McpContextServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        self.athlete = Athlete(name="Atleta MCP Service")
        self.db.add(self.athlete)
        self.db.commit()
        self.db.refresh(self.athlete)

        self.plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Base",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add(self.plan)
        self.db.commit()
        self.db.refresh(self.plan)

        self.goal = Goal(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            name="10K objetivo",
            event_date=date(2026, 6, 1),
            sport_type="running",
        )
        self.db.add(self.goal)
        self.db.commit()
        self.plan.goal_id = self.goal.id
        self.db.add(self.plan)
        self.db.commit()
        self.db.refresh(self.plan)

        day_1 = TrainingDay(athlete_id=self.athlete.id, training_plan_id=self.plan.id, day_date=date(2026, 5, 6))
        day_2 = TrainingDay(athlete_id=self.athlete.id, training_plan_id=self.plan.id, day_date=date(2026, 5, 7))
        self.db.add_all([day_1, day_2])
        self.db.commit()
        self.db.refresh(day_1)
        self.db.refresh(day_2)

        self.session = PlannedSession(
            athlete_id=self.athlete.id,
            training_day_id=day_1.id,
            name="Series 5x1000",
            sport_type="running",
            session_type="intervals",
            expected_duration_min=60,
            target_hr_zone="Z4",
            is_key_session=True,
        )
        self.next_session = PlannedSession(
            athlete_id=self.athlete.id,
            training_day_id=day_2.id,
            name="Rodaje suave",
            sport_type="running",
            session_type="easy",
            expected_duration_min=45,
            target_hr_zone="Z2",
        )
        self.db.add_all([self.session, self.next_session])
        self.db.commit()
        self.db.refresh(self.session)
        self.db.refresh(self.next_session)

        self.activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=12345,
            activity_name="Series en pista",
            sport_type="running",
            start_time=datetime(2026, 5, 6, 7, 0, tzinfo=timezone.utc),
            duration_sec=3600,
            distance_m=11000,
            avg_hr=165,
            training_load=180,
        )
        self.db.add(self.activity)
        self.db.commit()
        self.db.refresh(self.activity)

        self.db.add(
            ActivitySessionMatch(
                athlete_id=self.athlete.id,
                garmin_activity_id_fk=self.activity.id,
                planned_session_id_fk=self.session.id,
                training_day_id_fk=self.session.training_day_id,
                match_confidence=0.95,
                match_method="auto",
            )
        )
        self.db.add(
            SessionAnalysis(
                athlete_id=self.athlete.id,
                planned_session_id=self.session.id,
                activity_id=self.activity.id,
                status="completed",
                analysis_version="v2",
                summary_short="Buena ejecucion general.",
                coach_conclusion="Sesion bien resuelta.",
                next_recommendation="Mantener manana suave.",
                compliance_score=85,
                execution_score=82,
            )
        )
        self.db.add(
            DailyHealthMetric(
                athlete_id=self.athlete.id,
                metric_date=date(2026, 5, 6),
                sleep_duration_minutes=480,
                resting_hr=50,
                hrv_value=60.0,
                stress_avg=20,
                body_battery_morning=75,
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_build_session_feedback_payload_returns_expected_shape(self) -> None:
        payload = build_session_feedback_payload(
            self.db,
            athlete=self.athlete,
            training_plan=self.plan,
            target_date=date(2026, 5, 6),
        )

        self.assertEqual(payload["schema_version"], "mcp_session_feedback_v1")
        self.assertEqual(payload["planned_session"]["name"], "Series 5x1000")
        self.assertEqual(payload["completed_activity"]["name"], "Series en pista")
        self.assertEqual(payload["analysis"]["summary_short"], "Buena ejecucion general.")

    def test_build_week_context_payload_returns_expected_shape(self) -> None:
        payload = build_week_context_payload(
            self.db,
            athlete=self.athlete,
            training_plan=self.plan,
            reference_date=date(2026, 5, 6),
        )

        self.assertEqual(payload["schema_version"], "mcp_week_context_v1")
        self.assertIn("weekly_load_summary", payload)
        self.assertIn("planned_sessions", payload)

    def test_build_last_activity_feedback_payload_handles_missing_activity(self) -> None:
        self.db.delete(self.activity)
        self.db.commit()

        payload = build_last_activity_feedback_payload(
            self.db,
            athlete=self.athlete,
            training_plan=self.plan,
        )

        self.assertIsNone(payload["completed_activity"])
        self.assertIsNone(payload["analysis"])

    def test_build_next_session_context_payload_handles_missing_next_session(self) -> None:
        self.db.delete(self.next_session)
        self.db.commit()

        payload = build_next_session_context_payload(
            self.db,
            athlete=self.athlete,
            training_plan=self.plan,
            reference_date=date(2026, 5, 6),
        )

        self.assertEqual(payload["schema_version"], "mcp_next_session_context_v1")
        self.assertIsNone(payload["next_session"])
