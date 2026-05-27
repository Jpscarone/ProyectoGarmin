from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import garmin_account  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import scheduled_sync_job_log  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.garmin_account import GarminAccount
from app.db.models.planned_session import PlannedSession
from app.db.models.scheduled_sync_job_log import ScheduledSyncJobLog
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.activity_service import get_completed_activities_for_period
from app.services.garmin.client import GarminClient
from app.services.scheduled_sync_service import (
    JOB_TYPE_EVENING_FULL,
    JOB_TYPE_MORNING_HEALTH,
    SyncOperationResult,
    get_latest_scheduled_sync_overview,
    run_evening_full_job,
    run_morning_health_job,
    sync_health_for_athlete,
)


class ScheduledSyncServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.athlete = Athlete(name="Atleta Sync", status="active", timezone="America/Argentina/Buenos_Aires")
        self.db.add(self.athlete)
        self.db.commit()
        self.db.refresh(self.athlete)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_latest_scheduled_sync_overview_returns_last_jobs(self) -> None:
        self.db.add(
            ScheduledSyncJobLog(
                athlete_id=None,
                job_type=JOB_TYPE_MORNING_HEALTH,
                started_at=datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 5, 14, 10, 2, tzinfo=timezone.utc),
                status="success",
                message="Morning ok",
                health_days_synced=2,
            )
        )
        self.db.add(
            ScheduledSyncJobLog(
                athlete_id=None,
                job_type=JOB_TYPE_EVENING_FULL,
                started_at=datetime(2026, 5, 14, 22, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 5, 14, 22, 6, tzinfo=timezone.utc),
                status="partial_success",
                message="Evening parcial",
                activities_created=1,
            )
        )
        self.db.commit()

        overview = get_latest_scheduled_sync_overview(self.db)

        self.assertEqual(overview[JOB_TYPE_MORNING_HEALTH]["status"], "success")
        self.assertEqual(overview[JOB_TYPE_EVENING_FULL]["activities_created"], 1)

    def test_evening_job_is_skipped_when_same_type_is_running(self) -> None:
        self.db.add(
            ScheduledSyncJobLog(
                athlete_id=None,
                job_type=JOB_TYPE_EVENING_FULL,
                started_at=datetime.now(timezone.utc),
                status="running",
                message="running",
            )
        )
        self.db.commit()

        summary = run_evening_full_job(self.db)

        self.assertEqual(summary.status, "skipped")
        self.assertIn("Se omitio", summary.message)

    def test_stale_running_job_does_not_block_new_run(self) -> None:
        self.db.add(
            ScheduledSyncJobLog(
                athlete_id=None,
                job_type=JOB_TYPE_MORNING_HEALTH,
                started_at=datetime(2026, 5, 14, 6, 0, tzinfo=timezone.utc),
                status="running",
                message="viejo",
            )
        )
        self.db.commit()

        summary = run_morning_health_job(self.db, reference_date=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc).date())

        self.assertNotEqual(summary.message[:9], "Se omitio ")
        self.assertIn(summary.status, {"skipped", "success", "partial_success", "failed"})
        self.assertEqual(self.db.query(ScheduledSyncJobLog).count(), 2)

    def test_morning_job_continues_when_one_athlete_fails(self) -> None:
        second_athlete = Athlete(name="Atleta 2", status="active")
        self.db.add(second_athlete)
        self.db.commit()
        self.db.refresh(second_athlete)

        def fake_sync_health(db: Session, *, athlete_id: int, start_date, end_date, force: bool = False, settings=None):
            if athlete_id == second_athlete.id:
                raise RuntimeError("garmin down")
            return SyncOperationResult(status="success", message="ok", health_days_synced=2)

        with patch("app.services.scheduled_sync_service._get_target_athletes", return_value=[self.athlete, second_athlete]), \
            patch("app.services.scheduled_sync_service.sync_health_for_athlete", side_effect=fake_sync_health), \
            patch("app.services.scheduled_sync_service.generate_health_ai_if_needed", return_value=SyncOperationResult(status="skipped", message="exists")), \
            patch("app.services.scheduled_sync_service._recalculate_readiness", return_value=None):
            summary = run_morning_health_job(self.db, reference_date=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc).date())

        self.assertEqual(summary.status, "partial_success")
        self.assertEqual(summary.athletes_processed, 2)
        self.assertEqual(summary.athletes_succeeded, 1)
        self.assertEqual(summary.athletes_failed, 1)

    def test_evening_job_accumulates_pending_items_created(self) -> None:
        detection_summary = type("DetectionSummary", (), {"created_count": 2})()

        with patch("app.services.scheduled_sync_service._get_target_athletes", return_value=[self.athlete]), \
            patch("app.services.scheduled_sync_service._infer_activity_sync_start_date", return_value=datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc).date()), \
            patch("app.services.scheduled_sync_service.sync_activities_for_athlete", return_value=SyncOperationResult(status="success", message="ok", activities_created=1)), \
            patch("app.services.scheduled_sync_service.sync_health_for_athlete", return_value=SyncOperationResult(status="success", message="ok", health_days_synced=2)), \
            patch("app.services.scheduled_sync_service.auto_link_new_activities_for_athlete", return_value=SyncOperationResult(status="success", message="ok", activities_linked=1)), \
            patch("app.services.scheduled_sync_service.generate_missing_activity_analyses", return_value=SyncOperationResult(status="success", message="ok", activity_analyses_created=1)), \
            patch("app.services.scheduled_sync_service.update_weekly_analysis_if_needed", return_value=SyncOperationResult(status="success", message="ok", weekly_analyses_created=1)), \
            patch("app.services.scheduled_sync_service._recalculate_readiness", return_value=None), \
            patch("app.services.pending_training_service.detect_pending_items", return_value=detection_summary):
            summary = run_evening_full_job(self.db, reference_date=datetime(2026, 5, 14, 22, 0, tzinfo=timezone.utc).date())

        self.assertEqual(summary.status, "success")
        self.assertEqual(summary.pending_items_created, 2)
        self.assertEqual(summary.activities_created, 1)
        self.assertEqual(summary.activities_linked, 1)

    def test_morning_job_does_not_duplicate_health_ai_when_already_exists(self) -> None:
        with patch("app.services.scheduled_sync_service._get_target_athletes", return_value=[self.athlete]), \
            patch("app.services.scheduled_sync_service.sync_health_for_athlete", return_value=SyncOperationResult(status="success", message="ok", health_days_synced=2)), \
            patch("app.services.scheduled_sync_service.generate_health_ai_if_needed", return_value=SyncOperationResult(status="skipped", message="already exists")), \
            patch("app.services.scheduled_sync_service._recalculate_readiness", return_value=None):
            summary = run_morning_health_job(self.db, reference_date=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc).date())

        self.assertEqual(summary.status, "success")
        self.assertEqual(summary.health_ai_analyses_created, 0)

    def test_sync_health_for_athlete_without_garmin_is_skipped(self) -> None:
        summary = sync_health_for_athlete(
            self.db,
            athlete_id=self.athlete.id,
            start_date=date(2026, 5, 14),
            end_date=date(2026, 5, 14),
        )

        self.assertEqual(summary.status, "skipped")
        self.assertEqual(summary.message, "Atleta sin Garmin configurado")

    def test_morning_job_counts_athlete_without_garmin_as_skipped(self) -> None:
        configured = Athlete(name="Atleta Garmin", status="active", timezone="America/Argentina/Buenos_Aires")
        self.db.add(configured)
        self.db.commit()
        self.db.refresh(configured)
        self.db.add(
            GarminAccount(
                athlete_id=configured.id,
                garmin_email="configured@example.com",
                garmin_password_encrypted="cipher",
                token_dir="C:/tokens/configured",
                status="active",
                is_active=True,
            )
        )
        self.db.commit()

        def fake_sync_health(db: Session, *, athlete_id: int, start_date, end_date, force: bool = False, settings=None):
            if athlete_id == self.athlete.id:
                return SyncOperationResult(status="skipped", message="Atleta sin Garmin configurado")
            return SyncOperationResult(status="success", message="ok", health_days_synced=2)

        with patch("app.services.scheduled_sync_service.sync_health_for_athlete", side_effect=fake_sync_health), \
            patch("app.services.scheduled_sync_service.generate_health_ai_if_needed", return_value=SyncOperationResult(status="skipped", message="exists")), \
            patch("app.services.scheduled_sync_service._recalculate_readiness", return_value=None):
            summary = run_morning_health_job(self.db, reference_date=date(2026, 5, 14))

        self.assertEqual(summary.status, "success")
        self.assertEqual(summary.athletes_processed, 2)
        self.assertEqual(summary.athletes_succeeded, 1)
        self.assertEqual(summary.athletes_skipped, 1)
        self.assertEqual(summary.athletes_failed, 0)
        self.assertIn("1 omitido sin Garmin", summary.message)

    def test_completed_at_session_counts_as_completed_strength_session(self) -> None:
        plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan semanal",
            sport_type="running",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add(plan)
        self.db.flush()
        day = TrainingDay(
            training_plan_id=plan.id,
            athlete_id=self.athlete.id,
            day_date=date(2026, 5, 14),
            day_type="train",
        )
        self.db.add(day)
        self.db.flush()
        session = PlannedSession(
            training_day_id=day.id,
            athlete_id=self.athlete.id,
            sport_type="strength",
            name="Gimnasio",
            completed_at=datetime(2026, 5, 14, 21, 0, tzinfo=timezone.utc),
        )
        self.db.add(session)
        self.db.commit()

        garmin_activities, strength_sessions = get_completed_activities_for_period(
            self.db,
            self.athlete.id,
            date(2026, 5, 12),
            date(2026, 5, 18),
        )

        self.assertEqual(garmin_activities, [])
        self.assertEqual([item.id for item in strength_sessions], [session.id])

    def test_garmin_client_skips_display_name_dependent_payloads_when_identity_missing(self) -> None:
        class FakeApi:
            display_name = None

            def __init__(self) -> None:
                self.stats_calls = 0
                self.rhr_calls = 0

            def connectapi(self, path: str):
                return {}

            def get_stats(self, date_str: str):
                self.stats_calls += 1
                return {"calendarDate": date_str}

            def get_rhr_day(self, date_str: str):
                self.rhr_calls += 1
                return {"allMetrics": []}

            def get_sleep_data(self, date_str: str):
                return {}

            def get_stress_data(self, date_str: str):
                return {}

            def get_body_battery(self, start: str, end: str):
                return []

            def get_hrv_data(self, date_str: str):
                return {}

            def get_respiration_data(self, date_str: str):
                return {}

            def get_spo2_data(self, date_str: str):
                return {}

            def get_max_metrics(self, date_str: str):
                return {}

            def get_training_readiness(self, date_str: str):
                return {}

        api = FakeApi()
        client = GarminClient(api)

        with self.assertLogs("app.services.garmin.client", level="WARNING") as log_capture:
            payloads = client.get_health_payloads(date(2026, 5, 14))

        self.assertEqual(api.stats_calls, 0)
        self.assertEqual(api.rhr_calls, 0)
        self.assertEqual(payloads["daily_summary"], {})
        self.assertEqual(payloads["resting_hr"], {})
        self.assertTrue(any("Garmin user id unavailable; skipping health endpoint daily_summary." in line for line in log_capture.output))

    def test_garmin_client_continues_when_resting_hr_fails(self) -> None:
        class FakeApi:
            display_name = "athlete-one"

            def get_stats(self, date_str: str):
                return {"calendarDate": date_str, "steps": 1234}

            def get_rhr_day(self, date_str: str):
                raise RuntimeError("403 forbidden")

            def get_sleep_data(self, date_str: str):
                return {}

            def get_stress_data(self, date_str: str):
                return {}

            def get_body_battery(self, start: str, end: str):
                return []

            def get_hrv_data(self, date_str: str):
                return {}

            def get_respiration_data(self, date_str: str):
                return {}

            def get_spo2_data(self, date_str: str):
                return {}

            def get_max_metrics(self, date_str: str):
                return {}

            def get_training_readiness(self, date_str: str):
                return {}

        payloads = GarminClient(FakeApi()).get_health_payloads(date(2026, 5, 14))

        self.assertEqual(payloads["daily_summary"]["steps"], 1234)
        self.assertEqual(payloads["resting_hr"], {})


if __name__ == "__main__":
    unittest.main()
