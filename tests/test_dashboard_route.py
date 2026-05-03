from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.session import get_db
from app.main import app


class DashboardRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

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

    def test_dashboard_without_selected_athlete_shows_selector_cta(self) -> None:
        response = self.client.get("/", headers={"accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Selecciona un atleta para empezar", response.text)
        self.assertIn("/athletes/select", response.text)

    def test_dashboard_with_selected_athlete_renders_today_session(self) -> None:
        athlete = Athlete(name="Atleta Home")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        plan = TrainingPlan(
            athlete_id=athlete.id,
            name="Plan Home",
            sport_type="running",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 5, 20),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        day = TrainingDay(
            training_plan_id=plan.id,
            athlete_id=athlete.id,
            day_date=date(2026, 5, 2),
            day_type="train",
        )
        self.db.add(day)
        self.db.commit()
        self.db.refresh(day)
        session = PlannedSession(
            training_day_id=day.id,
            athlete_id=athlete.id,
            sport_type="running",
            name="Rodaje progresivo",
            expected_duration_min=70,
        )
        self.db.add(session)
        self.db.commit()

        response = self.client.get(
            f"/dashboard?athlete_id={athlete.id}&training_plan_id={plan.id}&selected_date=2026-05-02",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Estado actual de Atleta Home", response.text)
        self.assertIn("Rodaje progresivo", response.text)

    @patch("app.main.run_dashboard_auto_refresh")
    def test_dashboard_get_does_not_run_auto_refresh_directly(self, refresh_mock) -> None:
        athlete = Athlete(name="Atleta Home")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)

        response = self.client.get(
            f"/dashboard?athlete_id={athlete.id}&selected_date=2026-05-02",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        refresh_mock.assert_not_called()
        self.assertIn("Actualizando datos del atleta", response.text)

    def test_dashboard_renders_critical_alert_and_decision_block(self) -> None:
        athlete = Athlete(name="Atleta Critico")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        plan = TrainingPlan(
            athlete_id=athlete.id,
            name="Plan Critico",
            sport_type="running",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 5, 20),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        day = TrainingDay(
            training_plan_id=plan.id,
            athlete_id=athlete.id,
            day_date=date(2026, 5, 2),
            day_type="train",
        )
        self.db.add(day)
        self.db.flush()
        session = PlannedSession(
            training_day_id=day.id,
            athlete_id=athlete.id,
            sport_type="running",
            name="Series 8x400",
            session_type="intervals",
            expected_duration_min=60,
            is_key_session=True,
        )
        self.db.add(session)
        for offset in range(14):
            self.db.add(
                DailyHealthMetric(
                    athlete_id=athlete.id,
                    metric_date=date(2026, 5, 2) - timedelta(days=offset),
                    sleep_duration_minutes=300,
                    sleep_hours=5.0,
                    resting_hr=60,
                    hrv_value=35.0,
                    stress_avg=70,
                    body_battery_morning=25,
                    source="garmin",
                )
            )
        self.db.commit()

        response = self.client.get(
            f"/dashboard?athlete_id={athlete.id}&training_plan_id={plan.id}&selected_date=2026-05-02",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Decisión recomendada", response.text)
        self.assertIn("Alerta crítica", response.text)
        self.assertIn("Cuidado con la intensidad", response.text)

    def test_dashboard_auto_refresh_without_selected_athlete_returns_controlled_message(self) -> None:
        response = self.client.post("/dashboard/auto-refresh?selected_date=2026-05-02", headers={"accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Seleccioná un atleta para actualizar el dashboard.", response.text)

    @patch("app.main.run_dashboard_auto_refresh")
    def test_dashboard_auto_refresh_failure_still_returns_dashboard_partial(self, refresh_mock) -> None:
        athlete = Athlete(name="Atleta Auto")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        plan = TrainingPlan(
            athlete_id=athlete.id,
            name="Plan Auto",
            sport_type="running",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 5, 20),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        refresh_mock.side_effect = RuntimeError("garmin down")

        response = self.client.post(
            f"/dashboard/auto-refresh?athlete_id={athlete.id}&training_plan_id={plan.id}&selected_date=2026-05-02",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("No se pudo actualizar automáticamente", response.text)
        self.assertIn("dashboard-refresh-region", response.text)


if __name__ == "__main__":
    unittest.main()
