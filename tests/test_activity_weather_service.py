from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.models import activity_weather  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.activity_weather import ActivityWeather
from app.db.models.garmin_activity import GarminActivity
from app.services.garmin.activity_sync import sync_activities_by_date
from app.services.weather.weather_service import extract_weather_from_garmin_activity, sync_weather_for_activity


class ActivityWeatherServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.settings = Settings()

        athlete_row = Athlete(name="Atleta Clima")
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_extract_weather_from_garmin_activity_returns_none_when_values_are_invalid(self) -> None:
        payload = {
            "summaryDTO": {
                "temperature": 120,
                "humidity": 150,
                "windSpeed": 500,
            }
        }

        extracted = extract_weather_from_garmin_activity(payload)

        self.assertIsNone(extracted)

    @patch("app.services.garmin.activity_sync.GarminClient")
    @patch("app.services.garmin.activity_sync.get_garmin_auth_context")
    def test_garmin_activity_with_weather_saves_source_garmin_activity(self, auth_mock, client_cls_mock) -> None:
        auth_mock.return_value = SimpleNamespace(client=object())
        client_cls_mock.return_value = _FakeGarminClientWithWeather()

        sync_activities_by_date(
            self.db,
            self.settings,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            athlete_id=self.athlete.id,
        )

        weather = self.db.scalar(select(ActivityWeather))
        self.assertIsNotNone(weather)
        assert weather is not None
        self.assertEqual(weather.weather_source, "garmin_activity")
        self.assertEqual(weather.provider_name, "Garmin Activity")
        self.assertEqual(weather.temperature_start_c, 24.5)
        self.assertEqual(weather.humidity_start_pct, 68.0)

    @patch("app.services.garmin.activity_sync.GarminClient")
    @patch("app.services.garmin.activity_sync.get_garmin_auth_context")
    def test_activity_without_garmin_weather_does_not_create_weather_row(self, auth_mock, client_cls_mock) -> None:
        auth_mock.return_value = SimpleNamespace(client=object())
        client_cls_mock.return_value = _FakeGarminClientWithoutWeather()

        sync_activities_by_date(
            self.db,
            self.settings,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            athlete_id=self.athlete.id,
        )

        weather = self.db.scalar(select(ActivityWeather))
        self.assertIsNone(weather)

    @patch("app.services.weather.weather_service.OpenMeteoClient")
    def test_open_meteo_manual_sync_saves_source_open_meteo(self, client_cls_mock) -> None:
        client = client_cls_mock.return_value
        client.provider_name = "open-meteo"
        client.fetch_hourly_history.return_value = {
            "hourly": {
                "time": ["2026-05-01T09:00:00", "2026-05-01T10:00:00"],
                "temperature_2m": [18.0, 19.5],
                "apparent_temperature": [17.0, 18.0],
                "relative_humidity_2m": [70.0, 65.0],
                "dew_point_2m": [12.0, 12.5],
                "wind_speed_10m": [14.0, 16.0],
                "wind_direction_10m": [180.0, 190.0],
                "surface_pressure": [1012.0, 1011.0],
                "precipitation": [0.0, 0.0],
            }
        }
        activity = self._activity()

        result = sync_weather_for_activity(self.db, activity)

        self.assertTrue(result.created)
        self.db.refresh(activity)
        assert activity.weather is not None
        self.assertEqual(activity.weather.weather_source, "open_meteo")
        self.assertEqual(activity.weather.provider_name, "open-meteo")

    @patch("app.services.weather.weather_service.OpenMeteoClient")
    def test_open_meteo_does_not_overwrite_garmin_weather(self, client_cls_mock) -> None:
        client_cls_mock.return_value.fetch_hourly_history.return_value = {}
        activity = self._activity()
        activity.weather = ActivityWeather(
            garmin_activity_id=activity.id,
            provider_name="Garmin Activity",
            weather_source="garmin_activity",
            condition_summary="Sunny",
            temperature_start_c=25.0,
        )
        self.db.add(activity.weather)
        self.db.commit()

        result = sync_weather_for_activity(self.db, activity)

        self.assertFalse(result.created)
        self.assertFalse(result.updated)
        self.assertIn("clima nativo de Garmin", result.message)
        self.db.refresh(activity.weather)
        assert activity.weather is not None
        self.assertEqual(activity.weather.weather_source, "garmin_activity")
        self.assertEqual(activity.weather.temperature_start_c, 25.0)

    def _activity(self) -> GarminActivity:
        row = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=7001,
            activity_name="Rodaje clima",
            sport_type="running",
            start_time=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
            duration_sec=3600,
            distance_m=10000,
            start_lat=-32.95,
            start_lon=-60.66,
            is_multisport=False,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row


class _FakeGarminClientWithWeather:
    def get_activities_by_date(self, start_date: date, end_date: date, activitytype: str | None = None, sortorder: str | None = None) -> list[dict]:
        return [{"activityId": 9101, "activityName": "Rodaje con clima", "activityType": {"typeKey": "running"}}]

    def get_activity_summary(self, activity_id: int | str) -> dict:
        return {
            "activityId": int(activity_id),
            "activityName": "Rodaje con clima",
            "summaryDTO": {
                "startTimeLocal": "2026-05-01T09:00:00+00:00",
                "duration": 3600,
                "distance": 10000.0,
                "averageSpeed": 2.8,
                "temperature": 24.5,
                "humidity": 68,
                "windSpeed": 12.0,
                "weatherType": "Sunny",
            },
            "activityTypeDTO": {"typeKey": "running"},
        }

    def get_activity_details(self, activity_id: int | str) -> dict:
        return {"detailsDTO": {"apparentTemperature": 23.0, "windDirection": 140}}

    def get_activity_splits(self, activity_id: int | str) -> list[dict]:
        return []


class _FakeGarminClientWithoutWeather:
    def get_activities_by_date(self, start_date: date, end_date: date, activitytype: str | None = None, sortorder: str | None = None) -> list[dict]:
        return [{"activityId": 9102, "activityName": "Rodaje sin clima", "activityType": {"typeKey": "running"}}]

    def get_activity_summary(self, activity_id: int | str) -> dict:
        return {
            "activityId": int(activity_id),
            "activityName": "Rodaje sin clima",
            "summaryDTO": {
                "startTimeLocal": "2026-05-01T09:00:00+00:00",
                "duration": 3600,
                "distance": 10000.0,
                "averageSpeed": 2.8,
            },
            "activityTypeDTO": {"typeKey": "running"},
        }

    def get_activity_details(self, activity_id: int | str) -> dict:
        return {}

    def get_activity_splits(self, activity_id: int | str) -> list[dict]:
        return []


if __name__ == "__main__":
    unittest.main()
