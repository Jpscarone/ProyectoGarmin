from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
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
from app.db.models import scheduled_sync_job_log  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import user  # noqa: F401
from app.db.models import user_athlete_permission  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.scheduled_sync_job_log import ScheduledSyncJobLog
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.user import User  # noqa: F401
from app.db.models.user_athlete_permission import UserAthletePermission  # noqa: F401
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
        self.auth_bootstrap_patcher = patch("app.main.auth_is_bootstrapped", return_value=False)
        self.auth_gate_patcher = patch("app.main._should_authenticate", return_value=False)
        self.require_user_patcher = patch("app.services.athlete_context.require_current_user", side_effect=lambda request, db: object())
        self.list_athletes_patcher = patch(
            "app.services.athlete_context.list_accessible_athletes",
            side_effect=lambda db, user, only_active=True: list(db.query(Athlete).filter(Athlete.status != "archived").all()),
        )
        self.permission_patcher = patch("app.services.athlete_context.require_permission_for_athlete", return_value=None)
        self.auth_bootstrap_patcher.start()
        self.auth_gate_patcher.start()
        self.require_user_patcher.start()
        self.list_athletes_patcher.start()
        self.permission_patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.auth_bootstrap_patcher.stop()
        self.auth_gate_patcher.stop()
        self.require_user_patcher.stop()
        self.list_athletes_patcher.stop()
        self.permission_patcher.stop()
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

    def test_dashboard_shows_latest_scheduled_sync_summary(self) -> None:
        athlete = Athlete(name="Atleta Jobs")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        self.db.add(
            ScheduledSyncJobLog(
                athlete_id=None,
                job_type="morning_health",
                started_at=datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 5, 2, 10, 2, tzinfo=timezone.utc),
                status="success",
                message="1/1 atletas ok | salud 2 dias | health AI 1",
                health_days_synced=2,
                health_ai_analyses_created=1,
            )
        )
        self.db.add(
            ScheduledSyncJobLog(
                athlete_id=None,
                job_type="evening_full",
                started_at=datetime(2026, 5, 2, 22, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 5, 2, 22, 5, tzinfo=timezone.utc),
                status="partial_success",
                message="1/1 atletas ok | salud 2 dias | actividades +1",
                health_days_synced=2,
                activities_created=1,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/dashboard?athlete_id={athlete.id}&selected_date=2026-05-02",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Jobs automaticos", response.text)
        self.assertIn("Morning health", response.text)
        self.assertIn("Evening full", response.text)

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

    def test_dashboard_auto_refresh_with_selected_athlete_does_not_raise_name_error(self) -> None:
        athlete = Athlete(name="Atleta Refresh")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        plan = TrainingPlan(
            athlete_id=athlete.id,
            name="Plan Refresh",
            sport_type="running",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 5, 20),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)

        response = self.client.post(
            f"/dashboard/auto-refresh?athlete_id={athlete.id}&training_plan_id={plan.id}&selected_date=2026-05-02",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("name 'Athlete' is not defined", response.text)

    def test_dashboard_auto_refresh_keeps_all_step_labels_without_athlete_name_error(self) -> None:
        athlete = Athlete(name="Atleta Refresh Steps")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        plan = TrainingPlan(
            athlete_id=athlete.id,
            name="Plan Refresh Steps",
            sport_type="running",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 5, 20),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)

        response = self.client.post(
            f"/dashboard/auto-refresh?athlete_id={athlete.id}&training_plan_id={plan.id}&selected_date=2026-05-02",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Salud:", response.text)
        self.assertIn("Actividades:", response.text)
        self.assertIn("Vincul", response.text)
        self.assertIn("An", response.text)
        self.assertNotIn("name 'Athlete' is not defined", response.text)

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
