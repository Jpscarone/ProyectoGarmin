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
from app.db.models import athlete  # noqa: F401
from app.db.models import garmin_account  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.garmin_account import GarminAccount
from app.db.models.garmin_activity import GarminActivity
from app.services.activity_auto_sync_service import run_activity_auto_sync, should_auto_sync_activities
from app.services.garmin.activity_sync import GarminSyncResult, sync_activities_by_date


class ActivityAutoSyncServiceTests(unittest.TestCase):
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

        athlete_row = Athlete(name="Atleta Garmin")
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    @patch("app.services.activity_auto_sync_service.sync_activities_by_date")
    def test_auto_sync_without_previous_activities_uses_last_30_days(self, sync_mock) -> None:
        sync_mock.return_value = GarminSyncResult("Atleta Garmin", found=2, inserted=2, existing=0, errors=[])
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

        payload = run_activity_auto_sync(
            self.db,
            athlete=self.athlete,
            settings=self.settings,
            now=now,
        )

        self.assertTrue(payload["synced"])
        _, kwargs = sync_mock.call_args
        self.assertEqual(kwargs["start_date"], date(2026, 4, 1))
        self.assertEqual(kwargs["end_date"], date(2026, 5, 1))

    @patch("app.services.activity_auto_sync_service.sync_activities_by_date")
    def test_auto_sync_with_latest_activity_yesterday_starts_from_that_date(self, sync_mock) -> None:
        sync_mock.return_value = GarminSyncResult("Atleta Garmin", found=1, inserted=0, existing=1, errors=[])
        self._activity(
            garmin_activity_id=1001,
            start_time=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc),
        )
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

        payload = run_activity_auto_sync(
            self.db,
            athlete=self.athlete,
            settings=self.settings,
            now=now,
        )

        self.assertTrue(payload["synced"])
        _, kwargs = sync_mock.call_args
        self.assertEqual(kwargs["start_date"], date(2026, 4, 30))
        self.assertEqual(kwargs["end_date"], date(2026, 5, 1))

    def test_auto_sync_skips_when_latest_activity_is_today_local(self) -> None:
        self._activity(
            garmin_activity_id=1002,
            start_time=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )
        now = datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc)

        payload = run_activity_auto_sync(
            self.db,
            athlete=self.athlete,
            settings=self.settings,
            now=now,
        )

        self.assertFalse(payload["synced"])
        self.assertEqual(payload["reason"], "already_today")
        self.assertIn("ya es de hoy", payload["message"])

    def test_auto_sync_skips_when_cooldown_is_active(self) -> None:
        account = GarminAccount(
            athlete_id=self.athlete.id,
            status="active",
            last_activity_sync_at=datetime(2026, 5, 1, 11, 30, tzinfo=timezone.utc),
        )
        self.db.add(account)
        self.db.commit()
        self._activity(
            garmin_activity_id=1003,
            start_time=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc),
        )
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

        payload = run_activity_auto_sync(
            self.db,
            athlete=self.athlete,
            settings=self.settings,
            now=now,
        )

        self.assertFalse(payload["synced"])
        self.assertEqual(payload["reason"], "cooldown")
        self.assertIn("menos de 60 minutos", payload["message"])

    @patch("app.services.activity_auto_sync_service.sync_activities_by_date")
    def test_force_manual_sync_ignores_cooldown(self, sync_mock) -> None:
        sync_mock.return_value = GarminSyncResult("Atleta Garmin", found=1, inserted=1, existing=0, errors=[])
        account = GarminAccount(
            athlete_id=self.athlete.id,
            status="active",
            last_activity_sync_at=datetime(2026, 5, 1, 11, 30, tzinfo=timezone.utc),
        )
        self.db.add(account)
        self.db.commit()
        self._activity(
            garmin_activity_id=1004,
            start_time=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc),
        )
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

        payload = run_activity_auto_sync(
            self.db,
            athlete=self.athlete,
            settings=self.settings,
            force=True,
            now=now,
        )

        self.assertTrue(payload["synced"])
        sync_mock.assert_called_once()

    def test_should_auto_sync_uses_local_date_for_today_comparison(self) -> None:
        latest = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=1005,
            start_time=datetime(2026, 5, 1, 3, 30, tzinfo=timezone.utc),
            is_multisport=False,
        )
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

        decision = should_auto_sync_activities(None, latest, now=now)

        self.assertFalse(decision.should_sync)
        self.assertEqual(decision.reason, "already_today")

    @patch("app.services.garmin.activity_sync.GarminClient")
    @patch("app.services.garmin.activity_sync.get_garmin_auth_context")
    def test_sync_activities_by_date_is_idempotent_by_garmin_activity_id(self, auth_mock, client_cls_mock) -> None:
        auth_mock.return_value = SimpleNamespace(client=object())
        client_cls_mock.return_value = _FakeGarminClient()

        first = sync_activities_by_date(
            self.db,
            self.settings,
            start_date=date(2026, 4, 30),
            end_date=date(2026, 5, 1),
            athlete_id=self.athlete.id,
        )
        second = sync_activities_by_date(
            self.db,
            self.settings,
            start_date=date(2026, 4, 30),
            end_date=date(2026, 5, 1),
            athlete_id=self.athlete.id,
        )

        self.assertEqual(first.inserted, 1)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.existing, 1)
        rows = list(self.db.scalars(select(GarminActivity).where(GarminActivity.athlete_id == self.athlete.id)).all())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].garmin_activity_id, 9001)

    def _activity(self, *, garmin_activity_id: int, start_time: datetime) -> GarminActivity:
        row = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=garmin_activity_id,
            activity_name=f"Actividad {garmin_activity_id}",
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


class _FakeGarminClient:
    def get_activities_by_date(self, start_date: date, end_date: date, activitytype: str | None = None, sortorder: str | None = None) -> list[dict]:
        return [
            {
                "activityId": 9001,
                "activityName": "Rodaje Garmin",
                "startTimeLocal": "2026-04-30T09:00:00+00:00",
                "activityType": {"typeKey": "running"},
            }
        ]

    def get_activity_summary(self, activity_id: int | str) -> dict:
        return {
            "activityId": int(activity_id),
            "activityName": "Rodaje Garmin",
            "summaryDTO": {
                "startTimeLocal": "2026-04-30T09:00:00+00:00",
                "duration": 3600,
                "distance": 10000.0,
                "averageSpeed": 2.7777777778,
            },
            "activityTypeDTO": {"typeKey": "running"},
        }

    def get_activity_details(self, activity_id: int | str) -> dict:
        return {}

    def get_activity_splits(self, activity_id: int | str) -> list[dict]:
        return []


if __name__ == "__main__":
    unittest.main()
