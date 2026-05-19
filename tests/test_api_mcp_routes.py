from __future__ import annotations

import os
import unittest
from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import analysis_report  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import athlete_access_code  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import garmin_activity_lap  # noqa: F401
from app.db.models import goal  # noqa: F401
from app.db.models import health_ai_analysis  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import weekly_analysis  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.analysis_report import AnalysisReport
from app.db.models.athlete import Athlete
from app.db.models.athlete_access_code import AthleteAccessCode
from app.db.models.daily_health_metric import DailyHealthMetric
from app.db.models.garmin_activity import GarminActivity
from app.db.models.garmin_activity_lap import GarminActivityLap
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.session_analysis import SessionAnalysis
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.db.session import get_db
from app.main import app


class ApiMcpRoutesTests(unittest.TestCase):
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

        self.athlete = Athlete(name="Atleta MCP Routes")
        self.db.add(self.athlete)
        self.db.commit()
        self.db.refresh(self.athlete)
        self.db.add(
            AthleteAccessCode(
                athlete_id=self.athlete.id,
                access_code="ATLETA-MCP-1234",
                label="Atleta principal MCP",
                is_active=True,
            )
        )
        self.other_athlete = Athlete(name="Atleta ajeno MCP")
        self.db.add(self.other_athlete)
        self.db.commit()
        self.db.refresh(self.other_athlete)
        self.db.add_all(
            [
                AthleteAccessCode(
                    athlete_id=self.other_athlete.id,
                    access_code="ATLETA-INACTIVO-9999",
                    label="Inactivo",
                    is_active=False,
                ),
                AthleteAccessCode(
                    athlete_id=self.other_athlete.id,
                    access_code="OTRO-MCP-5678",
                    label="Atleta ajeno",
                    is_active=True,
                ),
            ]
        )
        self.db.commit()

        self.plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan MCP",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add(self.plan)
        self.db.commit()
        self.db.refresh(self.plan)

        self.db.add(
            TrainingDay(
                athlete_id=self.athlete.id,
                training_plan_id=self.plan.id,
                day_date=date(2026, 5, 7),
            )
        )
        self.db.commit()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer mcp-test-token"}

    def tearDown(self) -> None:
        if self.previous_token is None:
            os.environ.pop("MCP_API_TOKEN", None)
        else:
            os.environ["MCP_API_TOKEN"] = self.previous_token
        get_settings.cache_clear()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_session_feedback_works_without_activity(self) -> None:
        response = self.client.get(
            f"/api/mcp/session-feedback?date=2026-05-05&athlete_id={self.athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "mcp_session_feedback_v1")
        self.assertIsNone(payload["completed_activity"])
        self.assertIsNone(payload["analysis"])

    def test_ping_with_correct_token_returns_ok(self) -> None:
        response = self.client.get("/api/mcp/ping", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["app"], "training_app")

    def test_recent_activities_with_token_returns_200(self) -> None:
        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=555001,
                activity_name="Rodaje MCP",
                sport_type="running",
                duration_sec=3600,
                distance_m=10000,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/activities/recent?athlete_id={self.athlete.id}&limit=10",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete"]["id"], self.athlete.id)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["activities"][0]["activity_name"], "Rodaje MCP")

    def test_identify_me_returns_athlete_from_valid_access_code(self) -> None:
        response = self.client.get(
            "/api/mcp/me/identify?access_code=ATLETA-MCP-1234",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete"]["id"], self.athlete.id)
        self.assertEqual(payload["athlete"]["name"], self.athlete.name)
        access_row = self.db.scalar(select(AthleteAccessCode).where(AthleteAccessCode.access_code == "ATLETA-MCP-1234"))
        self.assertIsNotNone(access_row)
        assert access_row is not None
        self.assertIsNotNone(access_row.last_used_at)

    def test_identify_me_returns_401_for_invalid_access_code(self) -> None:
        response = self.client.get(
            "/api/mcp/me/identify?access_code=NOPE-0000",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Clave de acceso invalida.")

    def test_identify_me_returns_401_for_inactive_access_code(self) -> None:
        response = self.client.get(
            "/api/mcp/me/identify?access_code=ATLETA-INACTIVO-9999",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Clave de acceso invalida.")

    def test_my_recent_activities_only_returns_activities_for_access_code_athlete(self) -> None:
        self.db.add_all(
            [
                GarminActivity(
                    athlete_id=self.athlete.id,
                    garmin_activity_id=600001,
                    activity_name="Solo atleta correcto",
                    sport_type="running",
                    start_time=datetime(2026, 5, 18, 7, 0, 0),
                    duration_sec=1800,
                    distance_m=5000,
                ),
                GarminActivity(
                    athlete_id=self.other_athlete.id,
                    garmin_activity_id=600002,
                    activity_name="Atleta ajeno",
                    sport_type="running",
                    start_time=datetime(2026, 5, 18, 8, 0, 0),
                    duration_sec=2100,
                    distance_m=6000,
                ),
            ]
        )
        self.db.commit()

        response = self.client.get(
            "/api/mcp/me/activities/recent?access_code=ATLETA-MCP-1234&limit=10",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete"]["id"], self.athlete.id)
        self.assertEqual(payload["count"], 1)
        self.assertEqual([item["activity_name"] for item in payload["activities"]], ["Solo atleta correcto"])

    def test_my_day_overview_returns_planned_session_when_no_garmin_activity_exists(self) -> None:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 19),
            day_type="strength",
            day_notes="Dia liviano",
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)

        self.db.add(
            PlannedSession(
                athlete_id=self.athlete.id,
                training_day_id=training_day.id,
                name="Gimnasio suave",
                sport_type="strength",
                modality="indoor",
                expected_duration_min=45,
                session_order=1,
                target_notes="Movilidad y fuerza general suave",
            )
        )
        self.db.commit()

        response = self.client.get(
            "/api/mcp/me/day-overview?access_code=ATLETA-MCP-1234&date=19-05-2026",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["date"], "2026-05-19")
        self.assertIsNotNone(payload["training_day"])
        self.assertEqual(payload["training_day"]["date"], "2026-05-19")
        self.assertEqual(len(payload["planned_sessions"]), 1)
        self.assertEqual(payload["planned_sessions"][0]["name"], "Gimnasio suave")
        self.assertEqual(payload["planned_sessions"][0]["planned_duration_sec"], 2700)
        self.assertEqual(payload["planned_sessions"][0]["status"], "no_activity")
        self.assertEqual(payload["activities"], [])
        self.assertTrue(payload["summary"]["has_planned_sessions"])
        self.assertFalse(payload["summary"]["has_completed_activities"])
        self.assertEqual(
            payload["summary"]["message"],
            "Hay una sesión programada pero no hay actividad Garmin realizada asociada.",
        )

    def test_my_day_overview_marks_manual_strength_session_as_completed(self) -> None:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 23),
            day_type="strength",
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)

        session = PlannedSession(
            athlete_id=self.athlete.id,
            training_day_id=training_day.id,
            name="Gym completado",
            sport_type="strength",
            modality="indoor",
            expected_duration_min=50,
            session_order=1,
            completed_at=datetime(2026, 5, 23, 19, 30, 0),
            completion_source="manual",
            manual_duration_sec=3000,
        )
        self.db.add(session)
        self.db.commit()

        response = self.client.get(
            "/api/mcp/me/day-overview?access_code=ATLETA-MCP-1234&date=2026-05-23",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["planned_sessions"][0]["status"], "completed")
        self.assertEqual(len(payload["manual_sessions"]), 1)
        self.assertEqual(payload["manual_sessions"][0]["source"], "planned_session_manual")
        self.assertTrue(payload["summary"]["has_completed_activities"])

    def test_my_day_overview_returns_activity_when_no_planning_exists(self) -> None:
        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=700001,
                activity_name="Rodaje libre",
                sport_type="running",
                start_time=datetime(2026, 5, 20, 8, 0, 0),
                duration_sec=2400,
                distance_m=6200,
                avg_hr=142,
                training_load=48,
            )
        )
        self.db.commit()

        response = self.client.get(
            "/api/mcp/me/day-overview?access_code=ATLETA-MCP-1234&date=2026-05-20",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["date"], "2026-05-20")
        self.assertEqual(payload["planned_sessions"], [])
        self.assertEqual(len(payload["activities"]), 1)
        self.assertEqual(payload["activities"][0]["activity_name"], "Rodaje libre")
        self.assertFalse(payload["summary"]["has_planned_sessions"])
        self.assertTrue(payload["summary"]["has_completed_activities"])
        self.assertEqual(
            payload["summary"]["message"],
            "Hay actividad Garmin realizada pero no hay planificación asociada para esa fecha.",
        )

    def test_my_day_overview_returns_clear_summary_when_no_data_exists(self) -> None:
        response = self.client.get(
            "/api/mcp/me/day-overview?access_code=ATLETA-MCP-1234&date=2026-05-21",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["date"], "2026-05-21")
        self.assertIsNone(payload["training_day"])
        self.assertEqual(payload["planned_sessions"], [])
        self.assertEqual(payload["activities"], [])
        self.assertEqual(payload["matches"], [])
        self.assertEqual(
            payload["summary"]["message"],
            "No hay sesiones planificadas ni actividades Garmin registradas para esa fecha.",
        )

    def test_my_day_overview_only_returns_data_for_access_code_athlete(self) -> None:
        other_plan = TrainingPlan(
            athlete_id=self.other_athlete.id,
            name="Plan atleta ajeno",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add(other_plan)
        self.db.commit()
        self.db.refresh(other_plan)

        other_training_day = TrainingDay(
            athlete_id=self.other_athlete.id,
            training_plan_id=other_plan.id,
            day_date=date(2026, 5, 22),
            day_type="running",
        )
        self.db.add(other_training_day)
        self.db.commit()
        self.db.refresh(other_training_day)
        self.db.add(
            PlannedSession(
                athlete_id=self.other_athlete.id,
                training_day_id=other_training_day.id,
                name="Solo atleta ajeno",
                sport_type="running",
                modality="outdoor",
                expected_duration_min=30,
                session_order=1,
            )
        )
        self.db.add(
            GarminActivity(
                athlete_id=self.other_athlete.id,
                garmin_activity_id=700002,
                activity_name="Actividad ajena",
                sport_type="running",
                start_time=datetime(2026, 5, 22, 7, 0, 0),
                duration_sec=1800,
                distance_m=5000,
            )
        )
        self.db.commit()

        response = self.client.get(
            "/api/mcp/me/day-overview?access_code=ATLETA-MCP-1234&date=2026-05-22",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete"]["id"], self.athlete.id)
        self.assertEqual(payload["planned_sessions"], [])
        self.assertEqual(payload["activities"], [])

    def test_my_day_overview_returns_401_for_invalid_access_code(self) -> None:
        response = self.client.get(
            "/api/mcp/me/day-overview?access_code=NOPE-0000&date=2026-05-19",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Clave de acceso invalida.")

    def test_my_endpoints_reject_manual_athlete_id(self) -> None:
        response = self.client.get(
            f"/api/mcp/me/training/status?access_code=ATLETA-MCP-1234&athlete_id={self.other_athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "athlete_id no esta permitido en este endpoint.")

    def test_my_day_overview_rejects_manual_athlete_id(self) -> None:
        response = self.client.get(
            f"/api/mcp/me/day-overview?access_code=ATLETA-MCP-1234&date=2026-05-19&athlete_id={self.other_athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "athlete_id no esta permitido en este endpoint.")

    def test_week_context_returns_schema_version(self) -> None:
        response = self.client.get(f"/api/mcp/week-context?athlete_id={self.athlete.id}", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "mcp_week_context_v1")

    def test_last_activity_feedback_does_not_break_without_activity(self) -> None:
        response = self.client.get(
            f"/api/mcp/last-activity-feedback?athlete_id={self.athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "mcp_last_activity_feedback_v1")
        self.assertIsNone(payload["completed_activity"])
        self.assertIsNone(payload["analysis"])

    def test_next_session_context_does_not_break_without_next_session(self) -> None:
        response = self.client.get(
            f"/api/mcp/next-session-context?athlete_id={self.athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "mcp_next_session_context_v1")
        self.assertIsNone(payload["next_session"])

    def test_compare_planned_vs_done_uses_explicit_match_and_analysis(self) -> None:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 13),
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)

        planned_session = PlannedSession(
            athlete_id=self.athlete.id,
            training_day_id=training_day.id,
            name="Series en pista",
            sport_type="running",
            modality="outdoor",
            session_type="intervals",
            expected_duration_min=50,
            expected_distance_km=10,
            target_type="pace",
            target_notes="8x400m ritmo 5k",
            session_order=1,
        )
        self.db.add(planned_session)
        self.db.commit()
        self.db.refresh(planned_session)

        self.db.add(
            PlannedSessionStep(
                planned_session_id=planned_session.id,
                step_order=1,
                step_type="warmup",
                duration_sec=900,
            )
        )
        self.db.add(
            PlannedSessionStep(
                planned_session_id=planned_session.id,
                step_order=2,
                step_type="work",
                duration_sec=1800,
                distance_m=8000,
            )
        )
        self.db.add(
            PlannedSessionStep(
                planned_session_id=planned_session.id,
                step_order=3,
                step_type="cooldown",
                duration_sec=300,
                distance_m=2000,
            )
        )

        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=555777,
            activity_name="Pista miercoles",
            sport_type="running",
            modality="outdoor",
            start_time=datetime(2026, 5, 13, 7, 30, 0),
            duration_sec=3120,
            distance_m=9800,
            avg_hr=154,
            max_hr=176,
            avg_pace_sec_km=318,
            training_load=82,
            training_effect_aerobic=3.4,
            training_effect_anaerobic=2.1,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        match_row = ActivitySessionMatch(
            athlete_id=self.athlete.id,
            garmin_activity_id_fk=activity.id,
            planned_session_id_fk=planned_session.id,
            training_day_id_fk=training_day.id,
            match_confidence=0.96,
            match_method="manual",
        )
        self.db.add(match_row)
        self.db.add(
            SessionAnalysis(
                athlete_id=self.athlete.id,
                planned_session_id=planned_session.id,
                activity_id=activity.id,
                status="completed",
                summary_short="Cumplio bien la estructura principal.",
                coach_conclusion="Sesion bien resuelta y estable.",
                next_recommendation="Mantener el jueves muy suave.",
                compliance_score=88,
                execution_score=84,
            )
        )
        self.db.add(
            AnalysisReport(
                athlete_id=self.athlete.id,
                report_type="session",
                planned_session_id=planned_session.id,
                garmin_activity_id_fk=activity.id,
                title="Reporte de series",
                overall_status="correct",
                overall_score=86,
                summary_text="La carga estuvo alineada con lo esperado.",
                recommendation_text="Sostener la progresion semanal.",
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/compare/planned-vs-done?athlete_id={self.athlete.id}&activity_id={activity.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete"]["id"], self.athlete.id)
        self.assertEqual(payload["date"], "2026-05-13")
        self.assertEqual(payload["planned_session"]["id"], planned_session.id)
        self.assertEqual(payload["activity"]["id"], activity.id)
        self.assertEqual(payload["match"]["source"], "explicit")
        self.assertEqual(payload["match"]["match_id"], match_row.id)
        self.assertEqual(payload["analysis"]["adherence_score"], 88.0)
        self.assertEqual(payload["analysis"]["summary"], "Cumplio bien la estructura principal.")
        self.assertEqual(payload["analysis"]["recommendation"], "Mantener el jueves muy suave.")
        self.assertEqual(payload["differences"]["duration_delta_sec"], 120)
        self.assertEqual(payload["differences"]["distance_delta_m"], -200.0)

    def test_compare_planned_vs_done_returns_activity_without_programming(self) -> None:
        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=555999,
            activity_name="Rodaje libre",
            sport_type="running",
            modality="outdoor",
            start_time=datetime(2026, 5, 14, 8, 0, 0),
            duration_sec=2400,
            distance_m=7000,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        response = self.client.get(
            f"/api/mcp/compare/planned-vs-done?athlete_id={self.athlete.id}&activity_id={activity.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["planned_session"])
        self.assertEqual(payload["activity"]["id"], activity.id)
        self.assertEqual(payload["match"]["source"], "none")
        self.assertIn("No hay sesion programada asociada", payload["analysis"]["warnings"][0])

    def test_next_session_recommendation_returns_reduce_when_fatigue_signals_exist(self) -> None:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 13),
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)

        planned_session = PlannedSession(
            athlete_id=self.athlete.id,
            training_day_id=training_day.id,
            name="Tempo controlado",
            sport_type="running",
            modality="outdoor",
            session_type="tempo",
            expected_duration_min=45,
            expected_distance_km=9,
            target_notes="Trabajo en Z4 controlada",
            session_order=1,
            is_key_session=True,
        )
        self.db.add(planned_session)

        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=700001,
                activity_name="Series duras",
                sport_type="running",
                start_time=datetime(2026, 5, 12, 8, 0, 0),
                duration_sec=4200,
                distance_m=12000,
                avg_hr=158,
                max_hr=181,
                training_load=175,
                training_effect_aerobic=4.2,
                training_effect_anaerobic=2.6,
            )
        )

        self.db.add(
            DailyHealthMetric(
                athlete_id=self.athlete.id,
                metric_date=date(2026, 5, 13),
                sleep_duration_minutes=300,
                body_battery_morning=28,
                hrv_value=35.0,
                resting_hr=62,
                stress_avg=68,
            )
        )

        for offset in range(1, 6):
            self.db.add(
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 13).fromordinal(date(2026, 5, 13).toordinal() - offset),
                    sleep_duration_minutes=470,
                    body_battery_morning=72,
                    hrv_value=62.0,
                    resting_hr=50,
                    stress_avg=24,
                )
            )

        self.db.add(
            HealthAiAnalysis(
                athlete_id=self.athlete.id,
                reference_date=date(2026, 5, 13),
                summary="Fatiga reciente.",
                training_recommendation="Bajar intensidad hoy.",
                risk_level="high",
            )
        )
        self.db.add(
            WeeklyAnalysis(
                athlete_id=self.athlete.id,
                week_start_date=date(2026, 5, 12),
                week_end_date=date(2026, 5, 18),
                analysis_version="v2",
                status="completed",
                summary_short="Semana cargada.",
                total_duration_sec=15000,
                total_distance_m=36000,
                total_sessions=4,
                load_score=82,
                fatigue_score=79,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/next-session-recommendation?athlete_id={self.athlete.id}&reference_date=2026-05-13",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["next_session"]["id"], planned_session.id)
        self.assertEqual(payload["health"]["date"], "2026-05-13")
        self.assertEqual(payload["weekly"]["risk_level"], "moderate")
        self.assertIn(payload["recommendation"]["decision"], {"replace_easy", "reduce", "caution", "rest"})
        self.assertTrue(payload["data_quality"]["has_next_session"])
        self.assertTrue(payload["data_quality"]["has_health"])

    def test_next_session_recommendation_returns_no_data_without_session(self) -> None:
        response = self.client.get(
            f"/api/mcp/training/next-session-recommendation?athlete_id={self.athlete.id}&reference_date=2026-05-20",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["next_session"])
        self.assertEqual(payload["recommendation"]["decision"], "no_data")
        self.assertFalse(payload["data_quality"]["has_next_session"])

    def test_week_load_summary_returns_comparison_and_recommendation(self) -> None:
        current_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 12),
        )
        previous_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 5),
        )
        self.db.add_all([current_day, previous_day])
        self.db.commit()
        self.db.refresh(current_day)
        self.db.refresh(previous_day)

        self.db.add(
            PlannedSession(
                athlete_id=self.athlete.id,
                training_day_id=current_day.id,
                name="Fondo progresivo",
                sport_type="running",
                session_type="long",
                expected_duration_min=80,
                expected_distance_km=16,
                session_order=1,
            )
        )
        self.db.add(
            PlannedSession(
                athlete_id=self.athlete.id,
                training_day_id=previous_day.id,
                name="Rodaje base",
                sport_type="running",
                session_type="base",
                expected_duration_min=45,
                expected_distance_km=8,
                session_order=1,
            )
        )

        self.db.add_all(
            [
                GarminActivity(
                    athlete_id=self.athlete.id,
                    garmin_activity_id=800001,
                    activity_name="Bici fuerte",
                    sport_type="cycling",
                    start_time=datetime(2026, 5, 12, 8, 0, 0),
                    duration_sec=5400,
                    distance_m=45000,
                    avg_hr=142,
                    training_load=210,
                    training_effect_aerobic=4.1,
                    training_effect_anaerobic=1.2,
                ),
                GarminActivity(
                    athlete_id=self.athlete.id,
                    garmin_activity_id=800002,
                    activity_name="Running tempo",
                    sport_type="running",
                    start_time=datetime(2026, 5, 14, 7, 0, 0),
                    duration_sec=3600,
                    distance_m=11000,
                    avg_hr=156,
                    training_load=165,
                    training_effect_aerobic=4.3,
                    training_effect_anaerobic=2.3,
                ),
                GarminActivity(
                    athlete_id=self.athlete.id,
                    garmin_activity_id=800003,
                    activity_name="Semana previa",
                    sport_type="running",
                    start_time=datetime(2026, 5, 6, 7, 0, 0),
                    duration_sec=2400,
                    distance_m=7000,
                    avg_hr=138,
                    training_load=80,
                    training_effect_aerobic=2.5,
                    training_effect_anaerobic=0.2,
                ),
            ]
        )
        self.db.add_all(
            [
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 12),
                    sleep_duration_minutes=420,
                    body_battery_morning=58,
                    hrv_value=55,
                    resting_hr=52,
                ),
                DailyHealthMetric(
                    athlete_id=self.athlete.id,
                    metric_date=date(2026, 5, 14),
                    sleep_duration_minutes=390,
                    body_battery_morning=49,
                    hrv_value=50,
                    resting_hr=54,
                ),
            ]
        )
        self.db.add(
            WeeklyAnalysis(
                athlete_id=self.athlete.id,
                week_start_date=date(2026, 5, 11),
                week_end_date=date(2026, 5, 17),
                analysis_version="v2",
                status="completed",
                summary_short="Semana intensa pero util.",
                next_week_recommendation="Controlar la descarga.",
                load_score=78,
                fatigue_score=72,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/week-load-summary?athlete_id={self.athlete.id}&week_start_date=2026-05-11",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["week"]["start_date"], "2026-05-11")
        self.assertEqual(payload["week"]["completed_activities_count"], 2)
        self.assertTrue(payload["data_quality"]["has_activities"])
        self.assertTrue(payload["data_quality"]["has_health"])
        self.assertEqual(payload["weekly_analysis"]["risk_level"], "moderate")
        self.assertIsNotNone(payload["previous_week"])
        self.assertIsNotNone(payload["previous_week"]["delta_training_load"])
        self.assertIn(payload["recommendation"]["status"], {"balanced", "building", "high_load", "recovery_needed", "underloaded"})

    def test_week_load_summary_handles_missing_data(self) -> None:
        response = self.client.get(
            f"/api/mcp/training/week-load-summary?athlete_id={self.athlete.id}&week_start_date=2026-05-11&compare_previous=false",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["data_quality"]["has_activities"])
        self.assertFalse(payload["data_quality"]["has_health"])
        self.assertEqual(payload["recommendation"]["status"], "no_data")

    def test_week_load_summary_counts_manual_strength_sessions(self) -> None:
        day_one = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 12),
            day_type="strength",
        )
        day_two = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 15),
            day_type="strength",
        )
        self.db.add_all([day_one, day_two])
        self.db.commit()
        self.db.refresh(day_one)
        self.db.refresh(day_two)
        self.db.add_all(
            [
                PlannedSession(
                    athlete_id=self.athlete.id,
                    training_day_id=day_one.id,
                    name="Gym A",
                    sport_type="strength",
                    modality="indoor",
                    expected_duration_min=45,
                    session_order=1,
                    completed_at=datetime(2026, 5, 12, 20, 0, 0),
                    completion_source="manual",
                    manual_duration_sec=2700,
                ),
                PlannedSession(
                    athlete_id=self.athlete.id,
                    training_day_id=day_two.id,
                    name="Gym B",
                    sport_type="gym",
                    modality="indoor",
                    expected_duration_min=40,
                    session_order=1,
                    completed_at=datetime(2026, 5, 15, 20, 0, 0),
                    completion_source="manual",
                    manual_duration_sec=2400,
                ),
            ]
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/week-load-summary?athlete_id={self.athlete.id}&week_start_date=2026-05-11&compare_previous=false",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["week"]["garmin_activities_count"], 0)
        self.assertEqual(payload["week"]["completed_manual_sessions_count"], 2)
        self.assertEqual(payload["week"]["completed_strength_sessions_count"], 2)
        self.assertEqual(payload["week"]["total_completed_training_count"], 2)
        self.assertEqual(payload["week"]["completed_activities_count"], 2)
        self.assertEqual(payload["sports_breakdown"]["strength"]["planned_count"], 2)
        self.assertEqual(payload["sports_breakdown"]["strength"]["completed_count"], 2)
        self.assertEqual(payload["sports_breakdown"]["strength"]["manual_completed_count"], 2)
        self.assertEqual(payload["sports_breakdown"]["strength"]["total_duration_sec"], 5100)
        self.assertEqual(len(payload["manual_sessions"]), 2)
        self.assertEqual(payload["summary"]["counts"]["strength"], 2)
        self.assertIn("2 sesiones manuales de gimnasio/fuerza", payload["summary"]["week_narrative"])
        self.assertTrue(payload["data_quality"]["has_manual_sessions"])
        self.assertTrue(payload["data_quality"]["has_activities"])
        self.assertEqual(payload["recommendation"]["status"], "balanced")

    def test_week_load_summary_counts_running_garmin_plus_manual_strength(self) -> None:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 14),
            day_type="strength",
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)
        self.db.add(
            PlannedSession(
                athlete_id=self.athlete.id,
                training_day_id=training_day.id,
                name="Gym complementario",
                sport_type="strength",
                modality="indoor",
                expected_duration_min=35,
                session_order=1,
                completed_at=datetime(2026, 5, 14, 18, 0, 0),
                completion_source="manual",
                manual_duration_sec=2100,
            )
        )
        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=930001,
                activity_name="Rodaje semana",
                sport_type="running",
                start_time=datetime(2026, 5, 13, 7, 0, 0),
                duration_sec=3600,
                distance_m=10000,
                training_load=75,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/week-load-summary?athlete_id={self.athlete.id}&week_start_date=2026-05-11&compare_previous=false",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["week"]["garmin_activities_count"], 1)
        self.assertEqual(payload["week"]["completed_manual_sessions_count"], 1)
        self.assertEqual(payload["week"]["total_completed_training_count"], 2)
        self.assertEqual(payload["week"]["completed_strength_sessions_count"], 1)
        self.assertEqual(payload["sports_breakdown"]["running"]["completed_count"], 1)
        self.assertEqual(payload["sports_breakdown"]["strength"]["completed_count"], 1)
        self.assertEqual(
            payload["summary"]["week_narrative"],
            "Esa semana registraste 1 actividades Garmin y 1 sesiones manuales de gimnasio/fuerza. Total: 2 entrenamientos.",
        )

    def test_week_load_summary_does_not_duplicate_strength_session_with_garmin_match(self) -> None:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 16),
            day_type="strength",
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)

        planned_session = PlannedSession(
            athlete_id=self.athlete.id,
            training_day_id=training_day.id,
            name="Strength con match",
            sport_type="strength",
            modality="indoor",
            expected_duration_min=50,
            session_order=1,
        )
        self.db.add(planned_session)
        self.db.commit()
        self.db.refresh(planned_session)

        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=930002,
            activity_name="Strength Garmin",
            sport_type="strength_training",
            start_time=datetime(2026, 5, 16, 9, 0, 0),
            duration_sec=3000,
            training_load=40,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        self.db.add(
            ActivitySessionMatch(
                athlete_id=self.athlete.id,
                garmin_activity_id_fk=activity.id,
                planned_session_id_fk=planned_session.id,
                training_day_id_fk=training_day.id,
                match_confidence=0.95,
                match_method="manual",
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/week-load-summary?athlete_id={self.athlete.id}&week_start_date=2026-05-11&compare_previous=false",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["week"]["garmin_activities_count"], 1)
        self.assertEqual(payload["week"]["completed_manual_sessions_count"], 0)
        self.assertEqual(payload["week"]["completed_strength_sessions_count"], 1)
        self.assertEqual(payload["week"]["total_completed_training_count"], 1)
        self.assertEqual(payload["sports_breakdown"]["strength"]["activities_count"], 1)
        self.assertEqual(payload["sports_breakdown"]["strength"]["manual_completed_count"], 0)
        self.assertEqual(payload["sports_breakdown"]["strength"]["completed_count"], 1)
        self.assertEqual(payload["manual_sessions"], [])

    def test_my_week_load_summary_only_returns_manual_sessions_for_access_code_athlete(self) -> None:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 12),
            day_type="strength",
        )
        other_plan = TrainingPlan(
            athlete_id=self.other_athlete.id,
            name="Plan ajeno",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add_all([training_day, other_plan])
        self.db.commit()
        self.db.refresh(training_day)
        self.db.refresh(other_plan)
        other_training_day = TrainingDay(
            athlete_id=self.other_athlete.id,
            training_plan_id=other_plan.id,
            day_date=date(2026, 5, 13),
            day_type="strength",
        )
        self.db.add(other_training_day)
        self.db.commit()
        self.db.refresh(other_training_day)

        self.db.add_all(
            [
                PlannedSession(
                    athlete_id=self.athlete.id,
                    training_day_id=training_day.id,
                    name="Gym propio",
                    sport_type="strength",
                    modality="indoor",
                    expected_duration_min=45,
                    session_order=1,
                    completed_at=datetime(2026, 5, 12, 19, 0, 0),
                    completion_source="manual",
                    manual_duration_sec=2700,
                ),
                PlannedSession(
                    athlete_id=self.other_athlete.id,
                    training_day_id=other_training_day.id,
                    name="Gym ajeno",
                    sport_type="strength",
                    modality="indoor",
                    expected_duration_min=45,
                    session_order=1,
                    completed_at=datetime(2026, 5, 13, 19, 0, 0),
                    completion_source="manual",
                    manual_duration_sec=2700,
                ),
            ]
        )
        self.db.commit()

        response = self.client.get(
            "/api/mcp/me/training/week-load-summary?access_code=ATLETA-MCP-1234&week_start_date=2026-05-11&compare_previous=false",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete"]["id"], self.athlete.id)
        self.assertEqual(payload["week"]["completed_manual_sessions_count"], 1)
        self.assertEqual(len(payload["manual_sessions"]), 1)
        self.assertEqual(payload["manual_sessions"][0]["name"], "Gym propio")

    def test_week_load_summary_returns_zero_strength_counts_when_absent(self) -> None:
        self.db.add(
            GarminActivity(
                athlete_id=self.athlete.id,
                garmin_activity_id=930003,
                activity_name="Rodaje sin gym",
                sport_type="running",
                start_time=datetime(2026, 5, 12, 7, 0, 0),
                duration_sec=1800,
                distance_m=5000,
                training_load=30,
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/week-load-summary?athlete_id={self.athlete.id}&week_start_date=2026-05-11&compare_previous=false",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["week"]["completed_strength_sessions_count"], 0)
        self.assertEqual(payload["sports_breakdown"]["strength"]["planned_count"], 0)
        self.assertEqual(payload["sports_breakdown"]["strength"]["completed_count"], 0)
        self.assertEqual(payload["sports_breakdown"]["strength"]["manual_completed_count"], 0)

    def test_session_analysis_payload_returns_saved_analysis_and_laps(self) -> None:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=date(2026, 5, 15),
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)

        planned_session = PlannedSession(
            athlete_id=self.athlete.id,
            training_day_id=training_day.id,
            name="Intervalos 5x1000",
            sport_type="running",
            modality="outdoor",
            expected_duration_min=60,
            expected_distance_km=12,
            target_notes="Z4 controlada",
            session_order=1,
        )
        self.db.add(planned_session)
        self.db.commit()
        self.db.refresh(planned_session)

        self.db.add(
            PlannedSessionStep(
                planned_session_id=planned_session.id,
                step_order=1,
                step_type="work",
                repeat_count=5,
                duration_sec=240,
                target_type="pace",
                target_pace_zone="Z4",
                target_notes="5x1000",
            )
        )

        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=910001,
            activity_name="Pista viernes",
            sport_type="running",
            modality="outdoor",
            start_time=datetime(2026, 5, 15, 7, 0, 0),
            duration_sec=3500,
            distance_m=11800,
            avg_hr=154,
            max_hr=178,
            avg_pace_sec_km=320,
            avg_power=280,
            normalized_power=295,
            avg_cadence=172,
            training_load=140,
            training_effect_aerobic=3.8,
            training_effect_anaerobic=2.0,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        self.db.add(
            GarminActivityLap(
                garmin_activity_id_fk=activity.id,
                lap_number=1,
                lap_type="work",
                duration_sec=238,
                distance_m=1000,
                avg_hr=160,
                max_hr=171,
                avg_pace_sec_km=238,
                avg_power=310,
                avg_cadence=178,
            )
        )
        self.db.add(
            ActivitySessionMatch(
                athlete_id=self.athlete.id,
                garmin_activity_id_fk=activity.id,
                planned_session_id_fk=planned_session.id,
                training_day_id_fk=training_day.id,
                match_confidence=0.95,
                match_method="manual",
            )
        )
        self.db.add(
            SessionAnalysis(
                athlete_id=self.athlete.id,
                planned_session_id=planned_session.id,
                activity_id=activity.id,
                status="completed",
                summary_short="Bloques bien resueltos.",
                coach_conclusion="Buena alineacion entre plan y ejecucion.",
                next_recommendation="Mantener recuperacion activa.",
                metrics_json={
                    "context": {
                        "activity_laps": [
                            {
                                "index": 1,
                                "lap_type": "work",
                                "duration_sec": 238,
                                "distance_m": 1000,
                                "avg_hr": 160,
                                "avg_pace_sec_km": 238,
                                "avg_power": 310,
                                "avg_cadence": 178,
                            }
                        ]
                    },
                    "metrics": {
                        "laps": {
                            "pairs": [
                                {
                                    "planned_step_order": 1,
                                    "activity_lap_index": 1,
                                    "chosen_match_reason": "distance_match",
                                    "total_penalty": 2,
                                    "rejected_candidates": [
                                        {
                                            "lap_index": 2,
                                            "reason": "lap 2 descartada",
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                },
                llm_json={
                    "provider": "openai",
                    "status": "completed",
                    "structured_output": {"overall_assessment": "correcto"},
                },
            )
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/analysis/session-payload?athlete_id={self.athlete.id}&planned_session_id={planned_session.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved_by"], "planned_session_id")
        self.assertEqual(payload["planned_session"]["id"], planned_session.id)
        self.assertEqual(payload["activity"]["id"], activity.id)
        self.assertEqual(len(payload["laps"]), 1)
        self.assertEqual(len(payload["step_vs_lap_comparison"]), 1)
        self.assertTrue(payload["data_quality"]["has_metrics_json"])
        self.assertTrue(payload["data_quality"]["has_llm_json"])

    def test_session_analysis_payload_handles_missing_analysis(self) -> None:
        activity = GarminActivity(
            athlete_id=self.athlete.id,
            garmin_activity_id=910002,
            activity_name="Actividad sin analisis",
            sport_type="running",
            start_time=datetime(2026, 5, 16, 8, 0, 0),
            duration_sec=1800,
            distance_m=5000,
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        response = self.client.get(
            f"/api/mcp/analysis/session-payload?athlete_id={self.athlete.id}&activity_id={activity.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved_by"], "activity_id")
        self.assertEqual(payload["activity"]["id"], activity.id)
        self.assertFalse(payload["data_quality"]["has_metrics_json"])
        self.assertIn("No hay SessionAnalysis guardado", " ".join(payload["data_quality"]["warnings"]))
