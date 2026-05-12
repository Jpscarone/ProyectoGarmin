from __future__ import annotations

import unittest
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.session import get_db
from app.main import app
from app.services.dashboard_service import _build_weekly_summary, build_dashboard_context


class StrengthManualCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        self.athlete = Athlete(name="Atleta Strength")
        self.db.add(self.athlete)
        self.db.commit()
        self.db.refresh(self.athlete)

        self.plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Fuerza",
            sport_type="running",
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add(self.plan)
        self.db.commit()
        self.db.refresh(self.plan)

        day = TrainingDay(
            training_plan_id=self.plan.id,
            athlete_id=self.athlete.id,
            day_date=date(2026, 5, 6),
        )
        self.db.add(day)
        self.db.commit()
        self.db.refresh(day)
        self.training_day = day

        self.session = PlannedSession(
            training_day_id=day.id,
            athlete_id=self.athlete.id,
            sport_type="strength",
            name="Gymnasio tren inferior",
            expected_duration_min=50,
            strength_focus="lower_body",
            strength_rpe=6,
        )
        self.db.add(self.session)
        self.db.commit()
        self.db.refresh(self.session)

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_mark_strength_session_complete_endpoint_saves_manual_completion(self) -> None:
        response = self.client.post(
            f"/planned_sessions/{self.session.id}/mark-complete",
            data={
                "manual_duration_min": "55",
                "manual_strength_rpe": "7",
                "manual_strength_focus": "lower_body",
                "manual_completion_notes": "Buena sesion",
                "return_to": "day",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        updated = self.db.get(PlannedSession, self.session.id)
        assert updated is not None
        self.assertEqual(updated.completion_source, "manual")
        self.assertEqual(updated.manual_duration_sec, 3300)
        self.assertEqual(updated.manual_strength_rpe, 7)
        self.assertEqual(updated.manual_strength_focus, "lower_body")
        self.assertEqual(updated.manual_completion_notes, "Buena sesion")
        self.assertIsNotNone(updated.completed_at)

    def test_dashboard_counts_manual_strength_completion_without_distance(self) -> None:
        response = self.client.post(
            f"/planned_sessions/{self.session.id}/mark-complete",
            data={
                "manual_duration_min": "50",
                "manual_strength_rpe": "6",
                "manual_strength_focus": "lower_body",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        summary = _build_weekly_summary(self.db, self.athlete.id, self.training_day.day_date)
        self.assertEqual(summary["planned_count"], 1)
        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(summary["total_duration_minutes"], 50)
        self.assertEqual(summary["total_distance_km"], 0)

        dashboard = build_dashboard_context(self.db, self.athlete, self.plan, self.training_day.day_date)
        self.assertIn("Realizada manualmente", dashboard["today_session"]["status_badges"])


if __name__ == "__main__":
    unittest.main()
