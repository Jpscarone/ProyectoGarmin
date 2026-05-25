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


class McpConversationalV3CTests(unittest.TestCase):
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

        self.athlete = Athlete(name="Atleta V3C")
        self.other_athlete = Athlete(name="Ajeno V3C")
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

    def test_low_risk_plan_adjustment_suggests_keep(self) -> None:
        day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "running")
        self._create_session(day, self.athlete, "Rodaje suave", sport_type="running", expected_duration_min=40)
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/plan-adjustment-suggestions?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["risk_level"], "unknown")
        # no health => unknown, so add health and re-check keep behavior

        self.db.add(
            DailyHealthMetric(
                athlete_id=self.athlete.id,
                metric_date=date(2026, 5, 25),
                sleep_score=82,
                body_battery_morning=78,
                stress_avg=18,
                resting_hr=50,
                hrv_avg_ms=65,
                hrv_status="balanced",
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/plan-adjustment-suggestions?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )
        payload = response.json()
        self.assertEqual(payload["risk_level"], "low")
        self.assertEqual(payload["suggestions"][0]["type"], "keep")

    def test_moderate_risk_suggests_reduce_optional_or_intensity(self) -> None:
        self._add_moderate_risk_health()
        optional_day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "cycling")
        intense_day = self._create_day(self.plan, self.athlete, date(2026, 5, 27), "running")
        self._create_session(optional_day, self.athlete, "Bici opcional", sport_type="cycling", expected_duration_min=50, session_type="optional")
        self._create_session(intense_day, self.athlete, "Series 5x1000", sport_type="running", expected_duration_min=60, target_notes="Z4", is_key_session=True)
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/plan-adjustment-suggestions?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )
        payload = response.json()
        self.assertEqual(payload["risk_level"], "moderate")
        self.assertIn(payload["suggestions"][0]["type"], {"cancel_optional", "reduce", "monitor"})
        self.assertTrue(any(item["type"] in {"cancel_optional", "reduce"} for item in payload["suggestions"]))

    def test_high_risk_suggests_cancel_optional_or_reduce(self) -> None:
        self._add_high_risk_health_and_load()
        optional_day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "cycling")
        intense_day = self._create_day(self.plan, self.athlete, date(2026, 5, 27), "running")
        self._create_session(optional_day, self.athlete, "Bici opcional", sport_type="cycling", expected_duration_min=60, session_type="optional")
        self._create_session(intense_day, self.athlete, "Tempo duro", sport_type="running", expected_duration_min=70, target_notes="tempo z4", is_key_session=True)
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/plan-adjustment-suggestions?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )
        payload = response.json()
        self.assertEqual(payload["risk_level"], "high")
        self.assertTrue(any(item["type"] in {"cancel_optional", "replace", "reduce"} for item in payload["suggestions"]))

    def test_next_session_decision_without_next_session_returns_message(self) -> None:
        response = self.client.get(
            f"/api/mcp/next-session-decision?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "No hay proxima sesion pendiente.")

    def test_optional_session_impact_for_optional_bike_is_low(self) -> None:
        day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "cycling")
        session = self._create_session(day, self.athlete, "Bici opcional", sport_type="cycling", expected_duration_min=60, session_type="optional")
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/optional-session-impact?athlete_id={self.athlete.id}&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["impact_level"], "low")

    def test_optional_session_impact_for_long_run_is_high(self) -> None:
        day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "running")
        session = self._create_session(day, self.athlete, "Fondo largo", sport_type="running", expected_duration_min=110)
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/optional-session-impact?athlete_id={self.athlete.id}&planned_session_id={session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["impact_level"], "high")

    def test_generate_import_cancel(self) -> None:
        day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "cycling")
        session = self._create_session(day, self.athlete, "Bici opcional", sport_type="cycling", expected_duration_min=60, session_type="optional")
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/generate-plan-adjustment-import-text?athlete_id={self.athlete.id}&adjustment_type=cancel_optional&planned_session_id={session.id}&reason=fatiga",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["generated"])
        self.assertIn("ACTION: cancel", payload["import_text"])
        self.assertIn(f"SESSION_ID: {session.id}", payload["import_text"])

    def test_generate_import_reduce(self) -> None:
        day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "running")
        session = self._create_session(day, self.athlete, "Tempo", sport_type="running", expected_duration_min=60)
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/generate-plan-adjustment-import-text?athlete_id={self.athlete.id}&adjustment_type=reduce_next&planned_session_id={session.id}&reason=fatiga",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["generated"])
        self.assertIn("ACTION: update", payload["import_text"])
        self.assertIn("BLOCK", payload["import_text"])
        self.assertIn("MODE: preview", payload["import_text"])

    def test_generate_import_returns_false_if_no_target(self) -> None:
        response = self.client.get(
            f"/api/mcp/generate-plan-adjustment-import-text?athlete_id={self.athlete.id}&adjustment_type=cancel_optional",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["generated"])

    def test_wrappers_access_code(self) -> None:
        day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "cycling")
        own = self._create_session(day, self.athlete, "Bici opcional", sport_type="cycling", expected_duration_min=60, session_type="optional")
        other_day = self._create_day(self.other_plan, self.other_athlete, date(2026, 5, 26), "running")
        self._create_session(other_day, self.other_athlete, "Ajena", sport_type="running", expected_duration_min=40)
        self.db.commit()

        paths = [
            "/api/mcp/me/plan-adjustment-suggestions?access_code=ATLETA-MCP-1234&reference_date=2026-05-25",
            "/api/mcp/me/next-session-decision?access_code=ATLETA-MCP-1234&reference_date=2026-05-25",
            f"/api/mcp/me/optional-session-impact?access_code=ATLETA-MCP-1234&planned_session_id={own.id}",
            "/api/mcp/me/generate-plan-adjustment-import-text?access_code=ATLETA-MCP-1234&adjustment_type=cancel_optional&reason=fatiga",
            "/api/mcp/me/training-decision-context?access_code=ATLETA-MCP-1234&reference_date=2026-05-25",
        ]

        for path in paths:
            response = self.client.get(path, headers=self.headers)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.json()["athlete"]["id"], self.athlete.id, path)

    def _add_moderate_risk_health(self) -> None:
        self.db.add_all(
            [
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 20),
                    sleep_score=66,
                    body_battery_morning=40,
                    stress_avg=42,
                    resting_hr=53,
                    hrv_avg_ms=54,
                    hrv_status="low",
                ),
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 25),
                    sleep_score=64,
                    body_battery_morning=34,
                    stress_avg=46,
                    resting_hr=54,
                    hrv_avg_ms=53,
                    hrv_status="low",
                ),
            ]
        )
        self.db.commit()

    def _add_high_risk_health_and_load(self) -> None:
        self.db.add_all(
            [
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 12),
                    sleep_score=80,
                    body_battery_morning=75,
                    stress_avg=20,
                    resting_hr=49,
                    hrv_avg_ms=66,
                    hrv_status="balanced",
                ),
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 25),
                    sleep_score=54,
                    body_battery_morning=30,
                    stress_avg=52,
                    resting_hr=57,
                    hrv_avg_ms=40,
                    hrv_status="low",
                ),
            ]
        )
        first_day = self._create_day(self.plan, self.athlete, date(2026, 5, 21), "running")
        second_day = self._create_day(self.plan, self.athlete, date(2026, 5, 24), "running")
        first_session = self._create_session(first_day, self.athlete, "Intervalos", sport_type="running", expected_duration_min=70, target_notes="z4", is_key_session=True)
        second_session = self._create_session(second_day, self.athlete, "Fondo", sport_type="running", expected_duration_min=100)
        self._create_activity_match(first_session, "Intervalos", datetime(2026, 5, 21, 7, 0, 0), 4200, training_load=170, training_effect_aerobic=4.2, training_effect_anaerobic=2.8)
        self._create_activity_match(second_session, "Fondo", datetime(2026, 5, 24, 7, 0, 0), 6000, training_load=180, training_effect_aerobic=4.0)
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
            garmin_activity_id=300000 + session.id,
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
