from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import activity_weather  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.activity_weather import ActivityWeather
from app.db.models.garmin_activity import GarminActivity
from app.db.models.training_plan import TrainingPlan
from app.db.session import get_db
from app.main import app


class ActivitiesRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        self.athlete = Athlete(name="Pablo")
        self.other_athlete = Athlete(name="Felipe")
        self.db.add_all([self.athlete, self.other_athlete])
        self.db.commit()
        self.db.refresh(self.athlete)
        self.db.refresh(self.other_athlete)

        self.plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Rosario 42Km",
            sport_type="running",
            start_date=date(2026, 4, 27),
            end_date=date(2026, 6, 28),
            status="active",
        )
        other_plan = TrainingPlan(
            athlete_id=self.other_athlete.id,
            name="Plan Felipe",
            sport_type="running",
            start_date=date(2026, 4, 27),
            end_date=date(2026, 6, 28),
            status="active",
        )
        self.db.add_all([self.plan, other_plan])
        self.db.commit()
        self.db.refresh(self.plan)

        self._activity(
            athlete_id=self.athlete.id,
            garmin_activity_id=1001,
            activity_name="Rodaje dentro del plan",
            start_time=datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc),
        )
        self._activity(
            athlete_id=self.athlete.id,
            garmin_activity_id=1002,
            activity_name="Rodaje fuera del plan",
            start_time=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
        )
        self._activity(
            athlete_id=self.other_athlete.id,
            garmin_activity_id=1003,
            activity_name="Actividad de otro atleta",
            start_time=datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc),
        )

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

    def test_activities_page_defaults_to_current_athlete_and_plan(self) -> None:
        response = self.client.get(
            f"/activities?athlete_id={self.athlete.id}",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Rodaje dentro del plan", response.text)
        self.assertNotIn("Rodaje fuera del plan", response.text)
        self.assertNotIn("Actividad de otro atleta", response.text)
        self.assertNotIn('name="athlete_id"', response.text)
        self.assertIn("Rosario 42Km", response.text)

    def test_activities_page_accepts_empty_query_ids_after_session_is_set(self) -> None:
        first = self.client.get(
            f"/activities?athlete_id={self.athlete.id}&training_plan_id={self.plan.id}",
            headers={"accept": "text/html"},
        )
        self.assertEqual(first.status_code, 200)

        second = self.client.get(
            "/activities?athlete_id=&training_plan_id=",
            headers={"accept": "text/html"},
        )

        self.assertEqual(second.status_code, 200)
        self.assertIn("Rodaje dentro del plan", second.text)
        self.assertNotIn("Input should be a valid integer", second.text)

    def test_activity_detail_shows_manual_weather_button_when_weather_is_missing(self) -> None:
        response = self.client.get(
            "/activities/1",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Sincronizar clima", response.text)
        self.assertIn("Sin datos", response.text)

    def test_activity_detail_hides_manual_weather_button_when_weather_comes_from_garmin(self) -> None:
        activity = self.db.get(GarminActivity, 1)
        assert activity is not None
        activity.weather = ActivityWeather(
            garmin_activity_id=activity.id,
            provider_name="Garmin Activity",
            weather_source="garmin_activity",
            condition_summary="Sunny",
            temperature_start_c=22.0,
        )
        self.db.add(activity.weather)
        self.db.commit()

        response = self.client.get(
            "/activities/1",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Garmin Activity", response.text)
        self.assertNotIn("Sincronizar clima", response.text)

    @patch("app.routers.activities.run_activity_auto_sync")
    def test_activities_page_shows_auto_sync_status_message(self, auto_sync_mock) -> None:
        auto_sync_mock.return_value = {
            "synced": True,
            "reason": "synced",
            "message": "Sincronizacion automatica realizada. Se encontraron 1 actividades nuevas / 0 actualizadas.",
            "sync_result": None,
            "state": None,
        }

        response = self.client.get(
            f"/activities?athlete_id={self.athlete.id}",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Sincronizacion automatica realizada.", response.text)
        auto_sync_mock.assert_called_once()

    @patch("app.routers.activities.run_activity_auto_sync")
    def test_activities_page_keeps_loading_when_auto_sync_errors(self, auto_sync_mock) -> None:
        auto_sync_mock.return_value = {
            "synced": False,
            "reason": "error",
            "message": "Error al sincronizar: Garmin no respondio.",
            "sync_result": None,
            "state": None,
        }

        response = self.client.get(
            f"/activities?athlete_id={self.athlete.id}",
            headers={"accept": "text/html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Error al sincronizar: Garmin no respondio.", response.text)
        self.assertIn("Rodaje dentro del plan", response.text)

    def _activity(self, *, athlete_id: int, garmin_activity_id: int, activity_name: str, start_time: datetime) -> GarminActivity:
        row = GarminActivity(
            athlete_id=athlete_id,
            garmin_activity_id=garmin_activity_id,
            activity_name=activity_name,
            sport_type="running",
            start_time=start_time,
            duration_sec=3600,
            distance_m=10000,
            is_multisport=False,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row


if __name__ == "__main__":
    unittest.main()
