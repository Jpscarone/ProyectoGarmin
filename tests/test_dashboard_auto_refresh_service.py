from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_account  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import health_sync_state  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.health_sync_state import HealthSyncState
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.services.dashboard_auto_refresh_service import run_dashboard_auto_refresh


class DashboardAutoRefreshServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.today = date.today()
        self.now = datetime.now(timezone.utc)
        self.athlete = Athlete(name="Atleta Refresh")
        self.db.add(self.athlete)
        self.db.commit()
        self.db.refresh(self.athlete)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_health_missing_today_runs_health_sync(self) -> None:
        plan = self._plan()
        with (
            patch("app.services.dashboard_auto_refresh_service.run_health_auto_sync") as sync_mock,
            patch("app.services.dashboard_auto_refresh_service.sync_activities_by_date") as activity_sync_mock,
        ):
            sync_mock.return_value = {"synced": True, "records_created": 1, "records_updated": 0}
            activity_sync_mock.return_value = SimpleNamespace(inserted=0, existing=0, errors=[])
            result = run_dashboard_auto_refresh(self.db, self.athlete, plan, self.today)

        step = self._step(result, "health_sync")
        self.assertEqual(step["status"], "done")
        sync_mock.assert_called_once()

    def test_health_recently_synced_is_skipped(self) -> None:
        plan = self._plan()
        self.db.add(
            DailyHealthMetric(
                athlete_id=self.athlete.id,
                metric_date=self.today,
                sleep_hours=7.5,
                updated_at=self.now,
                source="garmin",
            )
        )
        self.db.commit()
        with (
            patch("app.services.dashboard_auto_refresh_service.run_health_auto_sync") as sync_mock,
            patch("app.services.dashboard_auto_refresh_service.sync_activities_by_date") as activity_sync_mock,
        ):
            activity_sync_mock.return_value = SimpleNamespace(inserted=0, existing=0, errors=[])
            result = run_dashboard_auto_refresh(self.db, self.athlete, plan, self.today)

        step = self._step(result, "health_sync")
        self.assertEqual(step["status"], "skipped")
        sync_mock.assert_not_called()

    def test_session_without_activity_triggers_activity_sync(self) -> None:
        plan = self._plan()
        self._session(plan=plan, day_date=self.today, name="Rodaje")
        self._fresh_health(self.today)
        with (
            patch("app.services.dashboard_auto_refresh_service.sync_activities_by_date") as sync_mock,
            patch("app.services.dashboard_auto_refresh_service.run_health_auto_sync") as health_sync_mock,
        ):
            sync_mock.return_value = SimpleNamespace(inserted=1, existing=0, errors=[])
            result = run_dashboard_auto_refresh(self.db, self.athlete, plan, self.today)
            health_sync_mock.assert_not_called()

        step = self._step(result, "activity_sync")
        self.assertEqual(step["status"], "done")
        sync_mock.assert_called_once()

    def test_high_score_candidate_auto_links(self) -> None:
        plan = self._plan()
        session = self._session(plan=plan, day_date=self.today, name="Tempo")
        activity = self._activity(start_time=datetime.combine(self.today, datetime.min.time()).replace(hour=8, tzinfo=timezone.utc), activity_name="Act")
        self._fresh_health(self.today)
        with (
            patch("app.services.dashboard_auto_refresh_service.sync_activities_by_date") as sync_mock,
            patch("app.services.dashboard_auto_refresh_service.preview_activity_match") as preview_mock,
            patch("app.services.dashboard_auto_refresh_service.auto_match_activity") as auto_match_mock,
            patch("app.services.dashboard_auto_refresh_service.run_health_auto_sync") as health_sync_mock,
        ):
            sync_mock.return_value = SimpleNamespace(inserted=0, existing=1, errors=[])
            preview_mock.return_value = SimpleNamespace(status="matched", matched_session_id=session.id, score=90.0)
            result = run_dashboard_auto_refresh(self.db, self.athlete, plan, self.today)
            health_sync_mock.assert_not_called()

        step = self._step(result, "activity_linking")
        self.assertEqual(step["status"], "done")
        auto_match_mock.assert_called_once_with(self.db, activity.id, training_plan_id=plan.id)

    def test_ambiguous_candidates_do_not_auto_link(self) -> None:
        plan = self._plan()
        self._session(plan=plan, day_date=self.today, name="Tempo")
        self._activity(start_time=datetime.combine(self.today, datetime.min.time()).replace(hour=8, tzinfo=timezone.utc), activity_name="Act")
        self._fresh_health(self.today)
        with (
            patch("app.services.dashboard_auto_refresh_service.sync_activities_by_date") as sync_mock,
            patch("app.services.dashboard_auto_refresh_service.preview_activity_match") as preview_mock,
            patch("app.services.dashboard_auto_refresh_service.auto_match_activity") as auto_match_mock,
            patch("app.services.dashboard_auto_refresh_service.run_health_auto_sync") as health_sync_mock,
        ):
            sync_mock.return_value = SimpleNamespace(inserted=0, existing=1, errors=[])
            preview_mock.return_value = SimpleNamespace(status="ambiguous", matched_session_id=None, score=82.0)
            result = run_dashboard_auto_refresh(self.db, self.athlete, plan, self.today)
            health_sync_mock.assert_not_called()

        step = self._step(result, "activity_linking")
        self.assertEqual(step["status"], "skipped")
        auto_match_mock.assert_not_called()

    def test_linked_activity_without_analysis_runs_analysis(self) -> None:
        plan = self._plan()
        session = self._session(plan=plan, day_date=self.today, name="Fondo")
        activity = self._activity(start_time=datetime.combine(self.today, datetime.min.time()).replace(hour=8, tzinfo=timezone.utc), activity_name="Act")
        self.db.add(
            ActivitySessionMatch(
                athlete_id=self.athlete.id,
                garmin_activity_id_fk=activity.id,
                planned_session_id_fk=session.id,
                training_day_id_fk=session.training_day_id,
                match_confidence=0.95,
                match_method="auto",
            )
        )
        self.db.commit()
        self._fresh_health(self.today)
        with (
            patch("app.services.dashboard_auto_refresh_service.sync_activities_by_date") as sync_mock,
            patch("app.services.dashboard_auto_refresh_service.run_session_analysis") as analysis_mock,
            patch("app.services.dashboard_auto_refresh_service.run_health_auto_sync") as health_sync_mock,
        ):
            sync_mock.return_value = SimpleNamespace(inserted=0, existing=1, errors=[])
            result = run_dashboard_auto_refresh(self.db, self.athlete, plan, self.today)
            health_sync_mock.assert_not_called()

        step = self._step(result, "session_analysis")
        self.assertEqual(step["status"], "done")
        analysis_mock.assert_called_once_with(
            self.db,
            planned_session_id=session.id,
            activity_id=activity.id,
            trigger_source="dashboard_auto_refresh",
        )

    def test_garmin_failure_is_reported_without_crashing(self) -> None:
        plan = self._plan()
        self._session(plan=plan, day_date=self.today, name="Rodaje")
        self._fresh_health(self.today)
        with (
            patch("app.services.dashboard_auto_refresh_service.sync_activities_by_date", side_effect=RuntimeError("Garmin timeout")),
            patch("app.services.dashboard_auto_refresh_service.run_health_auto_sync") as health_sync_mock,
        ):
            result = run_dashboard_auto_refresh(self.db, self.athlete, plan, self.today)
            health_sync_mock.assert_not_called()

        step = self._step(result, "activity_sync")
        self.assertEqual(step["status"], "failed")
        self.assertFalse(result["ok"])

    def _plan(self) -> TrainingPlan:
        plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Refresh",
            sport_type="running",
            start_date=self.today - timedelta(days=4),
            end_date=self.today + timedelta(days=30),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _session(self, *, plan: TrainingPlan, day_date: date, name: str, session_type: str = "easy") -> PlannedSession:
        day = TrainingDay(
            training_plan_id=plan.id,
            athlete_id=self.athlete.id,
            day_date=day_date,
            day_type="train",
        )
        self.db.add(day)
        self.db.flush()
        session = PlannedSession(
            training_day_id=day.id,
            athlete_id=self.athlete.id,
            sport_type="running",
            name=name,
            session_type=session_type,
            expected_duration_min=60,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def _activity(self, *, start_time: datetime, activity_name: str) -> GarminActivity:
        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=int(start_time.timestamp()),
            activity_name=activity_name,
            sport_type="running",
            start_time=start_time,
            duration_sec=3600,
            distance_m=10000,
            is_multisport=False,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)
        return activity

    def _fresh_health(self, metric_date: date) -> None:
        self.db.add(
            DailyHealthMetric(
                athlete_id=self.athlete.id,
                metric_date=metric_date,
                sleep_hours=7.0,
                source="garmin",
                updated_at=self.now,
            )
        )
        self.db.add(
            HealthSyncState(
                athlete_id=self.athlete.id,
                source="garmin",
                status="success",
                last_attempt_at=self.now,
                last_success_at=self.now,
                last_synced_for_date=metric_date,
            )
        )
        self.db.commit()

    def _step(self, result: dict, key: str) -> dict:
        return next(step for step in result["steps"] if step["key"] == key)


if __name__ == "__main__":
    unittest.main()
