from __future__ import annotations

import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import athlete_access_code  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.athlete_access_code import AthleteAccessCode
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.session import get_db
from app.main import app


class TodayCoachBriefingTests(unittest.TestCase):
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

        self.athlete = Athlete(name="Atleta Briefing")
        self.other_athlete = Athlete(name="Atleta Ajeno Briefing")
        self.db.add_all([self.athlete, self.other_athlete])
        self.db.commit()
        self.db.refresh(self.athlete)
        self.db.refresh(self.other_athlete)
        self.db.add_all(
            [
                AthleteAccessCode(athlete_id=self.athlete.id, access_code="ATLETA-MCP-1234", label="main", is_active=True),
                AthleteAccessCode(athlete_id=self.other_athlete.id, access_code="OTRO-MCP-5678", label="other", is_active=True),
            ]
        )
        self.db.commit()

        self.plan = self._create_plan(self.athlete)
        self.other_plan = self._create_plan(self.other_athlete)

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

    def test_briefing_with_required_pending_session(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        self._create_session(today_day, self.athlete, "Rodaje controlado", sport_type="running", expected_duration_min=45)
        self._add_good_health()

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["today_sessions"]["remaining_required"]), 1)
        self.assertEqual(payload["today_sessions"]["remaining_required"][0]["name"], "Rodaje controlado")

    def test_briefing_with_optional_pending_session(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "cycling")
        self._create_session(today_day, self.athlete, "Bici opcional", sport_type="cycling", expected_duration_min=50, session_type="optional")

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["today_sessions"]["remaining_optional"]), 1)
        self.assertEqual(payload["today_sessions"]["remaining_optional"][0]["name"], "Bici opcional")

    def test_briefing_with_required_and_optional_same_day(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "mixed")
        self._create_session(today_day, self.athlete, "Series", sport_type="running", expected_duration_min=55)
        self._create_session(today_day, self.athlete, "Gym opcional", sport_type="strength", expected_duration_min=35, session_type="optional", session_order=2)

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["today_sessions"]["remaining_required"]), 1)
        self.assertEqual(len(payload["today_sessions"]["remaining_optional"]), 1)

    def test_briefing_without_sessions_today_still_returns_next_session(self) -> None:
        next_day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "running")
        self._create_session(next_day, self.athlete, "Tempo manana", sport_type="running", expected_duration_min=60, target_notes="tempo z4")

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["today_sessions"]["remaining_required"], [])
        self.assertEqual(payload["next_session"]["name"], "Tempo manana")

    def test_briefing_without_readiness_does_not_fail(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        self._create_session(today_day, self.athlete, "Rodaje", sport_type="running", expected_duration_min=40)

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["readiness"]["available"])
        self.assertIn("No hay datos", payload["readiness"]["summary"])

    def test_briefing_low_risk_returns_green(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        self._create_session(today_day, self.athlete, "Rodaje facil", sport_type="running", expected_duration_min=40)
        self._add_good_health()

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decision"]["overall"], "green")

    def test_briefing_moderate_risk_returns_yellow(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        self._create_session(today_day, self.athlete, "Tempo controlado", sport_type="running", expected_duration_min=55, target_notes="tempo z4")
        self._add_moderate_health()

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decision"]["overall"], "yellow")

    def test_briefing_high_risk_returns_red(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        today_session = self._create_session(today_day, self.athlete, "Fondo largo", sport_type="running", expected_duration_min=110, target_notes="fondo intenso")
        prev_day = self._create_day(self.plan, self.athlete, date(2026, 5, 24), "running")
        prev_session = self._create_session(prev_day, self.athlete, "Intervalos", sport_type="running", expected_duration_min=70, target_notes="z4", is_key_session=True)
        self._create_activity_match(prev_session, "Intervalos", datetime(2026, 5, 24, 7, 0, 0), 4200, training_load=180, training_effect_aerobic=4.2, training_effect_anaerobic=2.7)
        self._create_activity_match(today_session, "Fondo largo", datetime(2026, 5, 25, 7, 0, 0), 6600, training_load=190, training_effect_aerobic=4.0)
        self._add_high_health()

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decision"]["overall"], "red")

    def test_briefing_does_not_include_cancelled_as_pending(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        self._create_session(today_day, self.athlete, "Cancelada", sport_type="running", expected_duration_min=30, completion_source="cancelled")

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["today_sessions"]["remaining_required"], [])
        self.assertEqual(payload["today_sessions"]["remaining_optional"], [])

    def test_wrapper_access_code(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        other_day = self._create_day(self.other_plan, self.other_athlete, date(2026, 5, 25), "running")
        self._create_session(today_day, self.athlete, "Propia", sport_type="running", expected_duration_min=40)
        self._create_session(other_day, self.other_athlete, "Ajena", sport_type="running", expected_duration_min=40)

        response = self.client.get(
            "/api/mcp/my/today-coach-briefing?access_code=ATLETA-MCP-1234&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["athlete"]["id"], self.athlete.id)
        self.assertEqual(len(response.json()["today_sessions"]["remaining_required"]), 1)

    def test_endpoint_does_not_modify_db(self) -> None:
        today_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        self._create_session(today_day, self.athlete, "Rodaje", sport_type="running", expected_duration_min=40)
        before_sessions = list(self.db.scalars(select(PlannedSession)).all())

        response = self.client.get(
            f"/api/mcp/today-coach-briefing?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )
        after_sessions = list(self.db.scalars(select(PlannedSession)).all())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(before_sessions), len(after_sessions))

    def _add_good_health(self) -> None:
        self.db.add(
            DailyHealthMetric(
                athlete_id=self.athlete.id,
                metric_date=date(2026, 5, 25),
                sleep_score=83,
                body_battery_morning=78,
                stress_avg=18,
                resting_hr=49,
                hrv_avg_ms=66,
                hrv_status="balanced",
            )
        )
        self.db.commit()

    def _add_moderate_health(self) -> None:
        self.db.add(
            DailyHealthMetric(
                athlete_id=self.athlete.id,
                metric_date=date(2026, 5, 25),
                sleep_score=64,
                body_battery_morning=36,
                stress_avg=46,
                resting_hr=54,
                hrv_avg_ms=52,
                hrv_status="low",
            )
        )
        self.db.commit()

    def _add_high_health(self) -> None:
        self.db.add_all(
            [
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 18),
                    sleep_score=82,
                    body_battery_morning=74,
                    stress_avg=20,
                    resting_hr=49,
                    hrv_avg_ms=66,
                    hrv_status="balanced",
                ),
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 25),
                    sleep_score=54,
                    body_battery_morning=28,
                    stress_avg=52,
                    resting_hr=57,
                    hrv_avg_ms=40,
                    hrv_status="low",
                ),
            ]
        )
        self.db.commit()

    def _create_plan(self, athlete: Athlete) -> TrainingPlan:
        plan = TrainingPlan(
            athlete_id=athlete.id,
            name=f"Plan {athlete.name}",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
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
        session_order: int = 1,
        is_key_session: bool = False,
    ) -> PlannedSession:
        session = PlannedSession(
            athlete_id=athlete.id,
            training_day_id=day.id,
            name=name,
            sport_type=sport_type,
            modality="outdoor",
            expected_duration_min=expected_duration_min,
            session_order=session_order,
            session_type=session_type,
            target_notes=target_notes,
            completion_source=completion_source,
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
            garmin_activity_id=400000 + session.id,
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
        self.db.add(
            ActivitySessionMatch(
                athlete_id=session.athlete_id,
                garmin_activity_id_fk=activity.id,
                planned_session_id_fk=session.id,
                training_day_id_fk=session.training_day_id,
                match_confidence=0.95,
                match_method="manual",
            )
        )
        self.db.commit()
        self.db.refresh(activity)
        return activity
