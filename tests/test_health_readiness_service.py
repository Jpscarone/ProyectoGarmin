from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import health_sync_state  # noqa: F401
from app.db.models import goal  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.garmin_activity import GarminActivity
from app.db.models.health_sync_state import HealthSyncState
from app.db.models.goal import Goal
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.schemas.daily_health_metric import HealthDailyMetricCreate
from app.services.daily_health_metric_service import (
    create_or_update_daily_health_metric,
    get_health_metric_by_date,
    list_health_metrics_for_athlete_range,
)
from app.services.health_readiness_service import build_health_readiness_summary
from app.services.health_readiness_service import build_health_llm_json
from app.services.health_readiness_service import build_health_training_context
from app.services.health_readiness_service import evaluate_health_readiness
from app.services.health_auto_sync_service import build_health_sync_view, should_auto_sync_health
from app.services.health_ai_analysis_service import build_health_llm_json_hash, should_auto_run_health_ai_analysis


class HealthReadinessServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        athlete_row = Athlete(name="Atleta Salud")
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_create_update_and_list_daily_health_metrics(self) -> None:
        metric_date = date(2026, 4, 23)
        create_or_update_daily_health_metric(
            self.db,
            HealthDailyMetricCreate(
                athlete_id=self.athlete.id,
                date=metric_date,
                sleep_duration_minutes=450,
                sleep_score=82,
                resting_hr=49,
                hrv_value=63.0,
                hrv_status="balanced",
                stress_avg=22,
                body_battery_morning=76,
                body_battery_min=34,
                body_battery_max=81,
                training_load=310.0,
                source="garmin",
            ),
        )

        create_or_update_daily_health_metric(
            self.db,
            HealthDailyMetricCreate(
                athlete_id=self.athlete.id,
                date=metric_date,
                sleep_duration_minutes=480,
                sleep_score=85,
                resting_hr=47,
                hrv_value=65.0,
                hrv_status="balanced",
                stress_avg=20,
                body_battery_morning=78,
                body_battery_min=36,
                body_battery_max=84,
                training_load=295.0,
                source="garmin",
            ),
        )

        stored = get_health_metric_by_date(self.db, self.athlete.id, metric_date)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.sleep_duration_minutes, 480)
        self.assertEqual(stored.sleep_hours, 8.0)
        self.assertEqual(stored.body_battery_start, 78)
        self.assertEqual(stored.hrv_avg_ms, 65.0)

        rows = list_health_metrics_for_athlete_range(self.db, self.athlete.id, metric_date, metric_date)
        self.assertEqual(len(rows), 1)

    def test_should_auto_sync_health_true_without_state(self) -> None:
        self.assertTrue(
            should_auto_sync_health(
                None,
                datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc),
                date(2026, 4, 29),
            )
        )

    def test_should_auto_sync_health_false_when_success_is_fresh(self) -> None:
        state = HealthSyncState(
            athlete_id=self.athlete.id,
            source="garmin",
            status="success",
            last_success_at=datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc),
            last_synced_for_date=date(2026, 4, 29),
        )

        self.assertFalse(
            should_auto_sync_health(
                state,
                datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc),
                date(2026, 4, 29),
            )
        )

    def test_should_auto_sync_health_true_when_synced_date_is_old(self) -> None:
        state = HealthSyncState(
            athlete_id=self.athlete.id,
            source="garmin",
            status="success",
            last_success_at=datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc),
            last_synced_for_date=date(2026, 4, 28),
        )

        self.assertTrue(
            should_auto_sync_health(
                state,
                datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc),
                date(2026, 4, 29),
            )
        )

    def test_should_auto_sync_health_false_when_running(self) -> None:
        state = HealthSyncState(
            athlete_id=self.athlete.id,
            source="garmin",
            status="running",
            last_success_at=None,
        )

        self.assertFalse(
            should_auto_sync_health(
                state,
                datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc),
                date(2026, 4, 29),
            )
        )

    def test_should_auto_sync_health_uses_local_date_not_utc_date(self) -> None:
        state = HealthSyncState(
            athlete_id=self.athlete.id,
            source="garmin",
            status="success",
            last_success_at=datetime(2026, 4, 29, 19, 0, tzinfo=timezone.utc),
            last_synced_for_date=date(2026, 4, 29),
        )

        self.assertTrue(
            should_auto_sync_health(
                state,
                datetime(2026, 4, 30, 2, 30, tzinfo=timezone.utc),
                date(2026, 4, 29),
            )
        )

    def test_health_sync_view_formats_recent_utc_timestamp_as_local_today(self) -> None:
        state = HealthSyncState(
            athlete_id=self.athlete.id,
            source="garmin",
            status="success",
            last_success_at=datetime.now(timezone.utc),
            last_synced_for_date=date.today(),
            records_created=1,
            records_updated=2,
        )

        view = build_health_sync_view(state, should_auto_sync=False)

        self.assertIn("Salud sincronizada hoy a las", view["label"])
        self.assertEqual(view["detail"], "Creados 1 | Actualizados 2")

    def test_health_llm_json_hash_is_stable(self) -> None:
        payload_a = {"b": 2, "a": {"x": 1}}
        payload_b = {"a": {"x": 1}, "b": 2}

        self.assertEqual(build_health_llm_json_hash(payload_a), build_health_llm_json_hash(payload_b))

    def test_should_auto_run_health_ai_analysis_without_previous_analysis(self) -> None:
        self.assertTrue(should_auto_run_health_ai_analysis(None, "abc"))

    def test_should_auto_run_health_ai_analysis_true_when_previous_hash_is_missing(self) -> None:
        from app.db.models.health_ai_analysis import HealthAiAnalysis

        analysis = HealthAiAnalysis(
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 29),
            llm_json_hash=None,
        )

        self.assertTrue(should_auto_run_health_ai_analysis(analysis, "new"))

    def test_should_auto_run_health_ai_analysis_false_when_hash_matches(self) -> None:
        from app.db.models.health_ai_analysis import HealthAiAnalysis

        analysis = HealthAiAnalysis(
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 29),
            llm_json_hash="same",
        )

        self.assertFalse(should_auto_run_health_ai_analysis(analysis, "same"))

    def test_should_auto_run_health_ai_analysis_true_when_hash_changes(self) -> None:
        from app.db.models.health_ai_analysis import HealthAiAnalysis

        analysis = HealthAiAnalysis(
            athlete_id=self.athlete.id,
            reference_date=date(2026, 4, 29),
            llm_json_hash="old",
        )

        self.assertTrue(should_auto_run_health_ai_analysis(analysis, "new"))

    def test_health_readiness_summary_with_14_complete_days(self) -> None:
        reference_date = date(2026, 4, 23)
        for offset in range(14):
            metric_date = reference_date - timedelta(days=offset)
            self._store_metric(
                metric_date=metric_date,
                sleep_minutes=480,
                resting_hr=50,
                hrv_value=62.0,
                stress_avg=20,
                body_battery_morning=75,
            )

        summary = build_health_readiness_summary(self.db, self.athlete.id, reference_date)

        self.assertEqual(summary.available_days_14d, 14)
        self.assertEqual(summary.missing_days_14d, 0)
        self.assertEqual(summary.sleep_avg_7d, 8.0)
        self.assertEqual(summary.sleep_avg_14d, 8.0)
        self.assertEqual(summary.resting_hr_avg_14d, 50.0)
        self.assertEqual(summary.resting_hr_avg_3d, 50.0)
        self.assertEqual(summary.resting_hr_delta_3d_vs_14d, 0.0)
        self.assertEqual(summary.hrv_avg_14d, 62.0)
        self.assertEqual(summary.hrv_avg_7d, 62.0)
        self.assertEqual(summary.hrv_trend, "stable")

    def test_health_readiness_summary_with_incomplete_days(self) -> None:
        reference_date = date(2026, 4, 23)
        for offset in [0, 1, 3, 5, 8, 13]:
            self._store_metric(
                metric_date=reference_date - timedelta(days=offset),
                sleep_minutes=420,
                resting_hr=52,
                hrv_value=58.0,
                stress_avg=26,
                body_battery_morning=64,
            )

        summary = build_health_readiness_summary(self.db, self.athlete.id, reference_date)

        self.assertEqual(summary.available_days_14d, 6)
        self.assertEqual(summary.missing_days_14d, 8)
        self.assertEqual(summary.sleep_avg_14d, 7.0)
        self.assertEqual(summary.resting_hr_avg_14d, 52.0)

    def test_resting_hr_delta_detects_recent_rise(self) -> None:
        reference_date = date(2026, 4, 23)
        for offset in range(14):
            metric_date = reference_date - timedelta(days=offset)
            resting_hr = 56 if offset <= 2 else 48
            self._store_metric(
                metric_date=metric_date,
                sleep_minutes=450,
                resting_hr=resting_hr,
                hrv_value=60.0,
                stress_avg=25,
                body_battery_morning=68,
            )

        summary = build_health_readiness_summary(self.db, self.athlete.id, reference_date)

        self.assertGreater(summary.resting_hr_avg_3d or 0, summary.resting_hr_avg_14d or 0)
        self.assertGreater(summary.resting_hr_delta_3d_vs_14d or 0, 0)

    def test_hrv_trend_detects_recent_drop(self) -> None:
        reference_date = date(2026, 4, 23)
        for offset in range(14):
            metric_date = reference_date - timedelta(days=offset)
            hrv_value = 40.0 if offset <= 6 else 62.0
            self._store_metric(
                metric_date=metric_date,
                sleep_minutes=460,
                resting_hr=50,
                hrv_value=hrv_value,
                stress_avg=28,
                body_battery_morning=66,
            )

        summary = build_health_readiness_summary(self.db, self.athlete.id, reference_date)

        self.assertEqual(summary.hrv_trend, "down")
        self.assertLess(summary.hrv_avg_7d or 0, summary.hrv_avg_14d or 0)

    def test_health_readiness_without_sufficient_data(self) -> None:
        reference_date = date(2026, 4, 23)

        summary = build_health_readiness_summary(self.db, self.athlete.id, reference_date)

        self.assertEqual(summary.available_days_14d, 0)
        self.assertEqual(summary.missing_days_14d, 14)
        self.assertIsNone(summary.sleep_avg_7d)
        self.assertIsNone(summary.resting_hr_avg_3d)
        self.assertEqual(summary.hrv_trend, "insufficient_data")

    def test_readiness_green_with_good_data(self) -> None:
        summary = self._summary(
            sleep_avg_7d=7.6,
            sleep_avg_14d=7.5,
            resting_hr_avg_14d=49.0,
            resting_hr_avg_3d=49.5,
            resting_hr_delta_3d_vs_14d=0.5,
            hrv_avg_14d=62.0,
            hrv_avg_7d=63.0,
            hrv_trend="stable",
            stress_avg_3d=24.0,
            stress_avg_7d=26.0,
            body_battery_morning_avg_3d=74.0,
            body_battery_morning_avg_7d=72.0,
            available_days_14d=14,
            missing_days_14d=0,
        )

        evaluation = evaluate_health_readiness(summary)

        self.assertEqual(evaluation.readiness_status, "green")
        self.assertEqual(evaluation.readiness_label, "entrenar normal")
        self.assertEqual(evaluation.readiness_score, 100)

    def test_readiness_green_for_mild_low_sleep_only(self) -> None:
        summary = self._summary(
            sleep_avg_7d=6.4,
            sleep_avg_14d=6.8,
            resting_hr_avg_14d=49.0,
            resting_hr_avg_3d=50.0,
            resting_hr_delta_3d_vs_14d=1.0,
            hrv_avg_14d=62.0,
            hrv_avg_7d=61.0,
            hrv_trend="stable",
            stress_avg_3d=28.0,
            stress_avg_7d=30.0,
            body_battery_morning_avg_3d=72.0,
            body_battery_morning_avg_7d=70.0,
            available_days_14d=12,
            missing_days_14d=2,
        )

        evaluation = evaluate_health_readiness(summary)

        self.assertEqual(evaluation.readiness_status, "green")
        self.assertEqual(evaluation.readiness_score, 92)
        self.assertEqual(evaluation.main_limiter, "sleep")

    def test_readiness_orange_for_hrv_down_and_resting_hr_up(self) -> None:
        summary = self._summary(
            sleep_avg_7d=7.2,
            sleep_avg_14d=7.1,
            resting_hr_avg_14d=48.0,
            resting_hr_avg_3d=54.0,
            resting_hr_delta_3d_vs_14d=6.0,
            hrv_avg_14d=64.0,
            hrv_avg_7d=50.0,
            hrv_trend="down",
            stress_avg_3d=34.0,
            stress_avg_7d=30.0,
            body_battery_morning_avg_3d=58.0,
            body_battery_morning_avg_7d=61.0,
            available_days_14d=14,
            missing_days_14d=0,
        )

        evaluation = evaluate_health_readiness(summary)

        self.assertEqual(evaluation.readiness_status, "orange")
        self.assertEqual(evaluation.readiness_score, 64)
        self.assertEqual(evaluation.main_limiter, "hrv")

    def test_readiness_red_for_multiple_negative_markers(self) -> None:
        summary = self._summary(
            sleep_avg_7d=5.5,
            sleep_avg_14d=6.1,
            resting_hr_avg_14d=48.0,
            resting_hr_avg_3d=55.0,
            resting_hr_delta_3d_vs_14d=7.0,
            hrv_avg_14d=62.0,
            hrv_avg_7d=47.0,
            hrv_trend="down",
            stress_avg_3d=65.0,
            stress_avg_7d=52.0,
            body_battery_morning_avg_3d=28.0,
            body_battery_morning_avg_7d=42.0,
            available_days_14d=14,
            missing_days_14d=0,
        )

        evaluation = evaluate_health_readiness(summary)

        self.assertEqual(evaluation.readiness_status, "red")
        self.assertLess(evaluation.readiness_score or 100, 50)

    def test_readiness_insufficient_data_with_less_than_5_days(self) -> None:
        summary = self._summary(
            sleep_avg_7d=None,
            sleep_avg_14d=None,
            resting_hr_avg_14d=None,
            resting_hr_avg_3d=None,
            resting_hr_delta_3d_vs_14d=None,
            hrv_avg_14d=None,
            hrv_avg_7d=None,
            hrv_trend="insufficient_data",
            stress_avg_3d=None,
            stress_avg_7d=None,
            body_battery_morning_avg_3d=None,
            body_battery_morning_avg_7d=None,
            available_days_14d=4,
            missing_days_14d=10,
        )

        evaluation = evaluate_health_readiness(summary)

        self.assertEqual(evaluation.readiness_status, "insufficient_data")
        self.assertIsNone(evaluation.readiness_score)
        self.assertEqual(evaluation.data_quality, "poor")

    def test_main_limiter_prefers_hrv_on_tie(self) -> None:
        summary = self._summary(
            sleep_avg_7d=7.0,
            sleep_avg_14d=7.0,
            resting_hr_avg_14d=49.0,
            resting_hr_avg_3d=55.0,
            resting_hr_delta_3d_vs_14d=6.0,
            hrv_avg_14d=64.0,
            hrv_avg_7d=51.0,
            hrv_trend="down",
            stress_avg_3d=25.0,
            stress_avg_7d=24.0,
            body_battery_morning_avg_3d=71.0,
            body_battery_morning_avg_7d=70.0,
            available_days_14d=14,
            missing_days_14d=0,
        )

        evaluation = evaluate_health_readiness(summary)

        self.assertEqual(evaluation.main_limiter, "hrv")

    def test_main_limiter_prefers_resting_hr_when_it_is_worst(self) -> None:
        summary = self._summary(
            sleep_avg_7d=7.1,
            sleep_avg_14d=7.0,
            resting_hr_avg_14d=48.0,
            resting_hr_avg_3d=54.0,
            resting_hr_delta_3d_vs_14d=6.0,
            hrv_avg_14d=62.0,
            hrv_avg_7d=62.0,
            hrv_trend="stable",
            stress_avg_3d=25.0,
            stress_avg_7d=23.0,
            body_battery_morning_avg_3d=72.0,
            body_battery_morning_avg_7d=70.0,
            available_days_14d=14,
            missing_days_14d=0,
        )

        evaluation = evaluate_health_readiness(summary)

        self.assertEqual(evaluation.main_limiter, "resting_hr")

    def test_build_health_llm_json_includes_summary_and_evaluation(self) -> None:
        summary = self._summary()
        evaluation = evaluate_health_readiness(summary)

        payload = build_health_llm_json(
            self.athlete,
            summary,
            evaluation,
            summary.reference_date,
            training_context={"planned_session_type": "base"},
        )

        self.assertEqual(payload["schema_version"], "health_readiness_v1")
        self.assertIn("health_summary", payload)
        self.assertIn("readiness_local", payload)
        self.assertEqual(payload["readiness_local"]["readiness_status"], evaluation.readiness_status)
        self.assertEqual(payload["training_context"]["planned_session_type"], "base")

    def test_build_health_llm_json_accepts_none_training_context(self) -> None:
        summary = self._summary()
        evaluation = evaluate_health_readiness(summary)

        payload = build_health_llm_json(
            self.athlete,
            summary,
            evaluation,
            summary.reference_date,
            training_context=None,
        )

        self.assertEqual(payload["training_context"], {})

    def test_build_health_training_context_without_training_data_does_not_break(self) -> None:
        context = build_health_training_context(self.db, self.athlete.id, date(2026, 4, 23))

        self.assertEqual(context["planned_sessions_last_7d"], 0)
        self.assertEqual(context["completed_activities_last_7d"], 0)
        self.assertEqual(context["hard_sessions_last_7d"], 0)
        self.assertIsNone(context["last_activity_date"])
        self.assertFalse(context["race_week"])

    def test_build_health_training_context_with_recent_activity_sets_last_activity_date(self) -> None:
        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=1001,
                activity_name="Rodaje",
                sport_type="running",
                start_time=self._dt(2026, 4, 22, 8, 0),
                duration_sec=3600,
                distance_m=10000,
                training_effect_aerobic=2.4,
            )
        )
        self.db.commit()

        context = build_health_training_context(self.db, self.athlete.id, date(2026, 4, 23))

        self.assertEqual(context["completed_activities_last_7d"], 1)
        self.assertEqual(context["last_activity_date"], "2026-04-22")
        self.assertEqual(context["total_duration_minutes_last_7d"], 60.0)
        self.assertEqual(context["total_distance_km_last_7d"], 10.0)

    def test_build_health_training_context_infers_hard_sessions(self) -> None:
        plan = self._create_training_plan()
        day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=plan.id,
            day_date=date(2026, 4, 21),
        )
        self.db.add(day)
        self.db.commit()
        self.db.refresh(day)
        self.db.add(
            PlannedSession(
                athlete_id=self.athlete.id,
                training_day_id=day.id,
                name="Series Z4",
                sport_type="running",
                session_type="interval",
                expected_duration_min=45,
                target_notes="Z4",
                session_order=1,
            )
        )
        self.db.commit()

        context = build_health_training_context(self.db, self.athlete.id, date(2026, 4, 23))

        self.assertEqual(context["planned_sessions_last_7d"], 1)
        self.assertEqual(context["hard_sessions_last_7d"], 1)
        self.assertEqual(context["last_hard_session_date"], "2026-04-21")
        self.assertEqual(context["days_since_last_hard_session"], 2)

    def test_build_health_training_context_marks_race_week_for_next_goal(self) -> None:
        self.db.add(
            Goal(
                athlete_id=self.athlete.id,
                name="10K objetivo",
                goal_role="primary",
                sport_type="running",
                event_type="race",
                event_date=date(2026, 4, 26),
            )
        )
        self.db.commit()

        context = build_health_training_context(self.db, self.athlete.id, date(2026, 4, 23))

        self.assertTrue(context["race_week"])
        self.assertEqual(context["next_goal_name"], "10K objetivo")
        self.assertEqual(context["days_to_next_goal"], 3)

    def test_build_health_llm_json_includes_real_training_context(self) -> None:
        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=1002,
                activity_name="Trabajo tempo",
                sport_type="running",
                start_time=self._dt(2026, 4, 22, 8, 0),
                duration_sec=3000,
                distance_m=9000,
                training_effect_aerobic=3.8,
            )
        )
        self.db.commit()
        summary = self._summary(reference_date=date(2026, 4, 23))
        evaluation = evaluate_health_readiness(summary)
        context = build_health_training_context(self.db, self.athlete.id, summary.reference_date)

        payload = build_health_llm_json(
            self.athlete,
            summary,
            evaluation,
            summary.reference_date,
            training_context=context,
        )

        self.assertEqual(payload["training_context"]["completed_activities_last_7d"], 1)
        self.assertEqual(payload["training_context"]["last_activity_date"], "2026-04-22")
        self.assertEqual(payload["training_context"]["hard_sessions_last_7d"], 1)

    def _store_metric(
        self,
        *,
        metric_date: date,
        sleep_minutes: int,
        resting_hr: int,
        hrv_value: float,
        stress_avg: int,
        body_battery_morning: int,
    ) -> None:
        create_or_update_daily_health_metric(
            self.db,
            HealthDailyMetricCreate(
                athlete_id=self.athlete.id,
                date=metric_date,
                sleep_duration_minutes=sleep_minutes,
                sleep_score=80,
                resting_hr=resting_hr,
                hrv_value=hrv_value,
                hrv_status="balanced",
                stress_avg=stress_avg,
                body_battery_morning=body_battery_morning,
                body_battery_min=max(5, body_battery_morning - 35),
                body_battery_max=min(100, body_battery_morning + 8),
                training_load=280.0,
                source="garmin",
            ),
        )

    def _summary(self, **overrides):
        base = {
            "athlete_id": self.athlete.id,
            "reference_date": date(2026, 4, 23),
            "sleep_avg_7d": 7.5,
            "sleep_avg_14d": 7.5,
            "resting_hr_avg_14d": 50.0,
            "resting_hr_avg_3d": 50.0,
            "resting_hr_delta_3d_vs_14d": 0.0,
            "hrv_avg_14d": 62.0,
            "hrv_avg_7d": 62.0,
            "hrv_trend": "stable",
            "stress_avg_3d": 25.0,
            "stress_avg_7d": 25.0,
            "body_battery_morning_avg_3d": 72.0,
            "body_battery_morning_avg_7d": 72.0,
            "available_days_14d": 14,
            "missing_days_14d": 0,
        }
        base.update(overrides)
        from app.schemas.daily_health_metric import HealthReadinessSummary

        return HealthReadinessSummary(**base)

    def _create_training_plan(self) -> TrainingPlan:
        plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Salud",
            sport_type="running",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 5, 1),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    @staticmethod
    def _dt(year: int, month: int, day: int, hour: int, minute: int):
        from datetime import datetime

        return datetime(year, month, day, hour, minute)


if __name__ == "__main__":
    unittest.main()
