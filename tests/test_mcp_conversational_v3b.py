from __future__ import annotations

import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import athlete_access_code  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import goal  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.athlete_access_code import AthleteAccessCode
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.goal import Goal
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.session import get_db
from app.main import app


class McpConversationalV3BTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_token = os.environ.get("MCP_API_TOKEN")
        os.environ["MCP_API_TOKEN"] = "mcp-test-token"
        get_settings.cache_clear()

        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        self.today_patcher = patch("app.routers.api_mcp.today_local", return_value=date(2026, 5, 25))
        self.today_patcher.start()

        self.athlete = Athlete(name="Atleta V3B")
        self.other_athlete = Athlete(name="Atleta Ajeno V3B")
        self.db.add_all([self.athlete, self.other_athlete])
        self.db.commit()
        self.db.refresh(self.athlete)
        self.db.refresh(self.other_athlete)

        self.db.add_all(
            [
                AthleteAccessCode(
                    athlete_id=self.athlete.id,
                    access_code="ATLETA-MCP-1234",
                    label="Principal",
                    is_active=True,
                ),
                AthleteAccessCode(
                    athlete_id=self.other_athlete.id,
                    access_code="OTRO-MCP-5678",
                    label="Ajeno",
                    is_active=True,
                ),
            ]
        )
        self.db.commit()

        self.plan = self._create_plan(self.athlete, "Plan V3B")
        self.other_plan = self._create_plan(self.other_athlete, "Plan Ajeno")

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer mcp-test-token"}

    def tearDown(self) -> None:
        self.today_patcher.stop()
        if self.previous_token is None:
            os.environ.pop("MCP_API_TOKEN", None)
        else:
            os.environ["MCP_API_TOKEN"] = self.previous_token
        get_settings.cache_clear()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_week_comparison_compares_current_vs_previous(self) -> None:
        prev_day = self._create_day(self.plan, self.athlete, date(2026, 5, 18), "running")
        current_day_run = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        current_day_strength = self._create_day(self.plan, self.athlete, date(2026, 5, 27), "strength")

        prev_session = self._create_session(prev_day, self.athlete, "Rodaje previo", sport_type="running", expected_duration_min=30)
        self._create_activity_match(prev_session, "Rodaje previo", datetime(2026, 5, 18, 7, 0, 0), 1800)

        current_run = self._create_session(current_day_run, self.athlete, "Rodaje actual", sport_type="running", expected_duration_min=60)
        self._create_activity_match(current_run, "Rodaje actual", datetime(2026, 5, 25, 7, 0, 0), 3600)
        self._create_session(
            current_day_strength,
            self.athlete,
            "Fuerza actual",
            sport_type="strength",
            expected_duration_min=40,
            completed_at=datetime(2026, 5, 27, 19, 0, 0),
            completion_source="manual",
            manual_duration_sec=2400,
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/week-comparison?athlete_id={self.athlete.id}&week_start_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current"]["total_sessions"], 2)
        self.assertEqual(payload["previous"]["total_sessions"], 1)
        self.assertEqual(payload["delta"]["sessions"], 1)
        self.assertEqual(payload["delta"]["duration_minutes"], 70)
        self.assertEqual(payload["current"]["strength_sessions"], 1)

    def test_training_load_trend_returns_four_weeks_and_up_direction(self) -> None:
        week_starts = [date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18), date(2026, 5, 25)]
        durations = [30, 60, 90, 120]
        for week_start, minutes in zip(week_starts, durations, strict=True):
            day = self._create_day(self.plan, self.athlete, week_start, "running")
            session = self._create_session(day, self.athlete, f"Semana {week_start.isoformat()}", sport_type="running", expected_duration_min=minutes)
            self._create_activity_match(session, f"Semana {week_start.isoformat()}", datetime(week_start.year, week_start.month, week_start.day, 7, 0, 0), minutes * 60)
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training-load-trend?athlete_id={self.athlete.id}&weeks=4",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["weeks"], 4)
        self.assertEqual(len(payload["trend"]), 4)
        self.assertEqual(payload["trend_direction"], "up")
        self.assertEqual(payload["trend"][-1]["total_duration_minutes"], 120)

    def test_fatigue_risk_summary_with_health_data_returns_high(self) -> None:
        first_day = self._create_day(self.plan, self.athlete, date(2026, 5, 21), "running")
        second_day = self._create_day(self.plan, self.athlete, date(2026, 5, 24), "running")
        first_session = self._create_session(first_day, self.athlete, "Intervalos", sport_type="running", expected_duration_min=70, target_notes="Z4 duro")
        second_session = self._create_session(second_day, self.athlete, "Fondo largo", sport_type="running", expected_duration_min=100)
        self._create_activity_match(first_session, "Intervalos", datetime(2026, 5, 21, 7, 0, 0), 4200, training_load=170, training_effect_aerobic=4.2, training_effect_anaerobic=2.8)
        self._create_activity_match(second_session, "Fondo largo", datetime(2026, 5, 24, 7, 0, 0), 6000, training_load=190, training_effect_aerobic=4.0)

        self.db.add_all(
            [
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 12),
                    resting_hr=50,
                    stress_avg=24,
                    body_battery_morning=72,
                    sleep_score=82,
                    hrv_avg_ms=64,
                ),
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 20),
                    resting_hr=55,
                    stress_avg=48,
                    body_battery_morning=34,
                    sleep_score=58,
                    hrv_status="low",
                    hrv_avg_ms=42,
                ),
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 25),
                    resting_hr=57,
                    stress_avg=52,
                    body_battery_morning=30,
                    sleep_score=54,
                    hrv_status="low",
                    hrv_avg_ms=40,
                ),
            ]
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/fatigue-risk-summary?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["readiness"]["available"])
        self.assertEqual(payload["risk_level"], "high")
        self.assertGreaterEqual(payload["recent_load"]["hard_sessions_last_7_days"], 2)

    def test_fatigue_risk_summary_without_health_returns_unknown(self) -> None:
        response = self.client.get(
            f"/api/mcp/fatigue-risk-summary?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["readiness"]["available"])
        self.assertEqual(payload["risk_level"], "unknown")
        self.assertIn("No hay datos", " ".join(payload["reasons"]))

    def test_week_strategy_summary_infers_specific_week(self) -> None:
        week_start = date(2026, 5, 25)
        interval_day = self._create_day(self.plan, self.athlete, week_start, "running")
        long_day = self._create_day(self.plan, self.athlete, week_start + (2 * date.resolution), "running")
        easy_day = self._create_day(self.plan, self.athlete, week_start + (4 * date.resolution), "running")

        self._create_session(interval_day, self.athlete, "Series 6x1000", sport_type="running", expected_duration_min=70, target_notes="Umbral maraton", is_key_session=True)
        self._create_session(long_day, self.athlete, "Fondo largo", sport_type="running", expected_duration_min=120, target_notes="Ritmo maraton especifico", is_key_session=True)
        self._create_session(easy_day, self.athlete, "Rodaje suave", sport_type="running", expected_duration_min=45, session_type="optional")
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/week-strategy-summary?athlete_id={self.athlete.id}&week_start_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["strategy_label"], "specific")
        self.assertEqual(len(payload["key_sessions"]), 2)
        self.assertIsNotNone(payload["long_session"])
        self.assertEqual(payload["optional_sessions"][0]["name"], "Rodaje suave")

    def test_training_dashboard_with_partial_data_returns_panorama(self) -> None:
        prev_day = self._create_day(self.plan, self.athlete, date(2026, 5, 24), "running")
        next_day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "running")
        prev_session = self._create_session(prev_day, self.athlete, "Rodaje ayer", sport_type="running", expected_duration_min=40)
        self._create_activity_match(prev_session, "Rodaje ayer", datetime(2026, 5, 24, 8, 0, 0), 2400)
        self._create_session(next_day, self.athlete, "Tempo manana", sport_type="running", expected_duration_min=55, target_notes="Controlado")
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training-dashboard?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["reference_date"], "2026-05-25")
        self.assertIn("remaining_week_plan", payload)
        self.assertIn("fatigue_risk", payload)
        self.assertIn("next_session", payload)
        self.assertIsNotNone(payload["last_activity_summary"])
        self.assertIsInstance(payload["key_message"], str)

    def test_access_code_wrappers_resolve_only_target_athlete(self) -> None:
        own_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        other_day = self._create_day(self.other_plan, self.other_athlete, date(2026, 5, 25), "running")
        own_session = self._create_session(own_day, self.athlete, "Propia", sport_type="running", expected_duration_min=45)
        other_session = self._create_session(other_day, self.other_athlete, "Ajena", sport_type="running", expected_duration_min=45)
        self._create_activity_match(own_session, "Propia", datetime(2026, 5, 25, 7, 0, 0), 2700)
        self._create_activity_match(other_session, "Ajena", datetime(2026, 5, 25, 8, 0, 0), 2700)
        self.db.commit()

        checks = [
            ("/api/mcp/me/week-comparison?access_code=ATLETA-MCP-1234&week_start_date=2026-05-25", "athlete"),
            ("/api/mcp/me/training-load-trend?access_code=ATLETA-MCP-1234&weeks=4", "athlete"),
            ("/api/mcp/me/fatigue-risk-summary?access_code=ATLETA-MCP-1234&reference_date=2026-05-25", "athlete"),
            ("/api/mcp/me/week-strategy-summary?access_code=ATLETA-MCP-1234&week_start_date=2026-05-25", "athlete"),
            ("/api/mcp/me/training-dashboard?access_code=ATLETA-MCP-1234&reference_date=2026-05-25", "athlete"),
        ]

        for path, athlete_key in checks:
            response = self.client.get(path, headers=self.headers)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.json()[athlete_key]["id"], self.athlete.id, path)

    def test_empty_cases_return_warnings(self) -> None:
        response = self.client.get(
            f"/api/mcp/week-strategy-summary?athlete_id={self.athlete.id}&week_start_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["sessions_count"], 0)
        self.assertTrue(payload["warnings"])

    def _create_plan(self, athlete: Athlete, name: str) -> TrainingPlan:
        plan = TrainingPlan(
            athlete_id=athlete.id,
            name=name,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 6, 30),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _create_day(self, plan: TrainingPlan, athlete: Athlete, day_date: date, day_type: str) -> TrainingDay:
        day = TrainingDay(
            athlete_id=athlete.id,
            training_plan_id=plan.id,
            day_date=day_date,
            day_type=day_type,
        )
        self.db.add(day)
        self.db.commit()
        self.db.refresh(day)
        return day

    def _create_session(
        self,
        day: TrainingDay,
        athlete: Athlete,
        name: str,
        *,
        sport_type: str,
        expected_duration_min: int,
        session_type: str | None = None,
        target_notes: str | None = None,
        completion_source: str | None = None,
        completed_at: datetime | None = None,
        manual_duration_sec: int | None = None,
        is_key_session: bool = False,
    ) -> PlannedSession:
        session = PlannedSession(
            athlete_id=athlete.id,
            training_day_id=day.id,
            name=name,
            sport_type=sport_type,
            modality="outdoor",
            expected_duration_min=expected_duration_min,
            session_order=1,
            session_type=session_type,
            target_notes=target_notes,
            completion_source=completion_source,
            completed_at=completed_at,
            manual_duration_sec=manual_duration_sec,
            is_key_session=is_key_session,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def _create_activity_match(
        self,
        session: PlannedSession,
        activity_name: str,
        start_time: datetime,
        duration_sec: int,
        *,
        training_load: float | None = None,
        training_effect_aerobic: float | None = None,
        training_effect_anaerobic: float | None = None,
    ) -> GarminActivity:
        activity = GarminActivity(
            athlete_id=session.athlete_id,
            garmin_activity_id=200000 + session.id,
            activity_name=activity_name,
            sport_type=session.sport_type,
            start_time=start_time,
            duration_sec=duration_sec,
            distance_m=0,
            training_load=training_load,
            training_effect_aerobic=training_effect_aerobic,
            training_effect_anaerobic=training_effect_anaerobic,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        match = ActivitySessionMatch(
            athlete_id=session.athlete_id,
            garmin_activity_id_fk=activity.id,
            planned_session_id_fk=session.id,
            training_day_id_fk=session.training_day_id,
            match_confidence=0.95,
            match_method="manual",
        )
        self.db.add(match)
        self.db.commit()
        self.db.refresh(activity)
        return activity
