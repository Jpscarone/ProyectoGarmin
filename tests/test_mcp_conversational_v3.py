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
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import planned_session_step  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models.activity_session_match import ActivitySessionMatch
from app.db.models.athlete import Athlete
from app.db.models.athlete_access_code import AthleteAccessCode
from app.db.models.garmin_activity import GarminActivity
from app.db.models.planned_session import PlannedSession
from app.db.models.planned_session_step import PlannedSessionStep
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.session import get_db
from app.main import app


class McpConversationalV3Tests(unittest.TestCase):
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

        self.athlete = Athlete(name="Atleta Conversational")
        self.other_athlete = Athlete(name="Atleta Ajeno")
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

        self.plan = self._create_plan(self.athlete, "Plan principal")
        self.other_plan = self._create_plan(self.other_athlete, "Plan ajeno")

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

    def test_remaining_week_plan_splits_completed_remaining_optional_and_excludes_cancelled(self) -> None:
        completed_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        remaining_day = self._create_day(self.plan, self.athlete, date(2026, 5, 27), "running")
        optional_day = self._create_day(self.plan, self.athlete, date(2026, 5, 29), "strength")
        cancelled_day = self._create_day(self.plan, self.athlete, date(2026, 5, 30), "running")

        completed = self._create_session(completed_day, self.athlete, "Rodaje cumplido", sport_type="running", expected_duration_min=45)
        self._create_activity_match(completed, "Rodaje Garmin", datetime(2026, 5, 25, 7, 0, 0), 2700)
        self._create_session(remaining_day, self.athlete, "Series 5x1000", sport_type="running", expected_duration_min=60)
        self._create_session(
            optional_day,
            self.athlete,
            "Gym opcional",
            sport_type="strength",
            session_type="optional",
            expected_duration_min=40,
        )
        self._create_session(
            cancelled_day,
            self.athlete,
            "Rodaje cancelado",
            sport_type="running",
            expected_duration_min=30,
            completion_source="cancelled",
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/remaining-week-plan?athlete_id={self.athlete.id}&week_start_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["completed_sessions"], 1)
        self.assertEqual(payload["remaining_sessions"], 1)
        self.assertEqual(payload["optional_sessions"], 1)
        self.assertEqual(payload["remaining_volume_minutes"], 60)
        self.assertEqual([item["name"] for item in payload["sessions"]], ["Series 5x1000", "Gym opcional"])

    def test_remaining_week_plan_returns_empty_message(self) -> None:
        response = self.client.get(
            f"/api/mcp/training/remaining-week-plan?athlete_id={self.athlete.id}&week_start_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["remaining_sessions"], 0)
        self.assertEqual(payload["optional_sessions"], 0)
        self.assertEqual(payload["message"], "No quedan sesiones pendientes esta semana.")

    def test_previous_week_summary_aggregates_garmin_and_manual_strength_without_duplicates(self) -> None:
        run_day = self._create_day(self.plan, self.athlete, date(2026, 5, 19), "running")
        strength_day = self._create_day(self.plan, self.athlete, date(2026, 5, 21), "strength")
        cancelled_day = self._create_day(self.plan, self.athlete, date(2026, 5, 22), "running")

        run_session = self._create_session(run_day, self.athlete, "Rodaje semana pasada", sport_type="running", expected_duration_min=50)
        self._create_activity_match(run_session, "Rodaje semana pasada", datetime(2026, 5, 19, 7, 0, 0), 3000)
        self._create_session(
            strength_day,
            self.athlete,
            "Fuerza manual",
            sport_type="strength",
            expected_duration_min=45,
            completed_at=datetime(2026, 5, 21, 20, 0, 0),
            completion_source="manual",
            manual_duration_sec=2700,
        )
        self._create_session(
            cancelled_day,
            self.athlete,
            "Cancelada",
            sport_type="running",
            expected_duration_min=35,
            completion_source="cancelled",
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/previous-week-summary?athlete_id={self.athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["week_start_date"], "2026-05-18")
        self.assertEqual(payload["running_sessions"], 1)
        self.assertEqual(payload["strength_sessions"], 1)
        self.assertEqual(payload["cycling_sessions"], 0)
        self.assertEqual(payload["total_sessions"], 2)
        self.assertEqual(payload["total_duration_minutes"], 95)
        self.assertEqual(payload["adherence_percent"], 100.0)
        self.assertEqual(payload["completed_vs_planned"], "2/2")
        self.assertGreaterEqual(len(payload["highlights"]), 1)

    def test_next_planned_session_ignores_cancelled_and_returns_blocks(self) -> None:
        cancelled_day = self._create_day(self.plan, self.athlete, date(2026, 5, 26), "running")
        next_day = self._create_day(self.plan, self.athlete, date(2026, 5, 27), "running")
        self._create_session(
            cancelled_day,
            self.athlete,
            "Cancelada primero",
            sport_type="running",
            expected_duration_min=30,
            completion_source="cancelled",
        )
        next_session = self._create_session(
            next_day,
            self.athlete,
            "Series 6x800",
            sport_type="running",
            expected_duration_min=55,
            target_notes="Controlado",
        )
        self._create_step(next_session, step_order=1, step_type="warmup", duration_sec=900)
        self._create_step(next_session, step_order=2, step_type="work", repeat_count=6, distance_m=800, target_pace_zone="Z4")
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/next-planned-session?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["date"], "2026-05-27")
        self.assertEqual(payload["name"], "Series 6x800")
        self.assertEqual(len(payload["blocks"]), 2)

    def test_next_planned_session_returns_empty_message(self) -> None:
        response = self.client.get(
            f"/api/mcp/training/next-planned-session?athlete_id={self.athlete.id}&reference_date=2026-05-25",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "No hay sesiones pendientes.")

    def test_today_remaining_sessions_only_returns_pending_sessions(self) -> None:
        day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "mixed")
        completed = self._create_session(day, self.athlete, "Completada hoy", sport_type="running", expected_duration_min=35)
        self._create_activity_match(completed, "Completada hoy", datetime(2026, 5, 25, 8, 0, 0), 2100)
        self._create_session(day, self.athlete, "Pendiente hoy", sport_type="strength", expected_duration_min=40)
        self._create_session(
            day,
            self.athlete,
            "Cancelada hoy",
            sport_type="running",
            expected_duration_min=20,
            completion_source="cancelled",
        )
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/today-remaining-sessions?athlete_id={self.athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["remaining_count"], 1)
        self.assertEqual([item["name"] for item in payload["sessions"]], ["Pendiente hoy"])

    def test_week_adherence_counts_cancelled_and_missed_sessions(self) -> None:
        completed_day_one = self._create_day(self.plan, self.athlete, date(2026, 5, 18), "running")
        completed_day_two = self._create_day(self.plan, self.athlete, date(2026, 5, 19), "strength")
        cancelled_day = self._create_day(self.plan, self.athlete, date(2026, 5, 20), "running")
        missed_day = self._create_day(self.plan, self.athlete, date(2026, 5, 21), "cycling")

        completed_one = self._create_session(completed_day_one, self.athlete, "Completada 1", sport_type="running", expected_duration_min=40)
        self._create_activity_match(completed_one, "Completada 1", datetime(2026, 5, 18, 7, 0, 0), 2400)
        self._create_session(
            completed_day_two,
            self.athlete,
            "Completada 2",
            sport_type="strength",
            expected_duration_min=45,
            completed_at=datetime(2026, 5, 19, 19, 0, 0),
            completion_source="manual",
            manual_duration_sec=2700,
        )
        self._create_session(
            cancelled_day,
            self.athlete,
            "Cancelada",
            sport_type="running",
            expected_duration_min=30,
            completion_source="cancelled",
        )
        self._create_session(missed_day, self.athlete, "Perdida", sport_type="cycling", expected_duration_min=50)
        self.db.commit()

        response = self.client.get(
            f"/api/mcp/training/week-adherence?athlete_id={self.athlete.id}&week_start_date=2026-05-18",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["planned_sessions"], 4)
        self.assertEqual(payload["completed_sessions"], 2)
        self.assertEqual(payload["cancelled_sessions"], 1)
        self.assertEqual(payload["missed_sessions"], 1)
        self.assertEqual(payload["adherence_percent"], 66.7)

    def test_access_code_wrappers_resolve_only_the_target_athlete(self) -> None:
        own_day = self._create_day(self.plan, self.athlete, date(2026, 5, 25), "running")
        other_day = self._create_day(self.other_plan, self.other_athlete, date(2026, 5, 25), "running")
        self._create_session(own_day, self.athlete, "Propia hoy", sport_type="running", expected_duration_min=30)
        self._create_session(other_day, self.other_athlete, "Ajena hoy", sport_type="running", expected_duration_min=30)

        previous_day = self._create_day(self.plan, self.athlete, date(2026, 5, 18), "running")
        previous_session = self._create_session(previous_day, self.athlete, "Propia pasada", sport_type="running", expected_duration_min=30)
        self._create_activity_match(previous_session, "Propia pasada", datetime(2026, 5, 18, 7, 0, 0), 1800)
        self.db.commit()

        checks = [
            ("/api/mcp/me/training/remaining-week-plan?access_code=ATLETA-MCP-1234&week_start_date=2026-05-25", "remaining_sessions", 1),
            ("/api/mcp/me/training/previous-week-summary?access_code=ATLETA-MCP-1234", "total_sessions", 1),
            ("/api/mcp/me/training/next-planned-session?access_code=ATLETA-MCP-1234&reference_date=2026-05-25", "name", "Propia hoy"),
            ("/api/mcp/me/training/today-remaining-sessions?access_code=ATLETA-MCP-1234", "remaining_count", 1),
            ("/api/mcp/me/training/week-adherence?access_code=ATLETA-MCP-1234&week_start_date=2026-05-25", "planned_sessions", 1),
        ]

        for path, key, expected in checks:
            response = self.client.get(path, headers=self.headers)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.json()["athlete"]["id"], self.athlete.id, path)
            self.assertEqual(response.json()[key], expected, path)

    def _create_plan(self, athlete: Athlete, name: str) -> TrainingPlan:
        plan = TrainingPlan(
            athlete_id=athlete.id,
            name=name,
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
        completed_at: datetime | None = None,
        manual_duration_sec: int | None = None,
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
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def _create_step(self, session: PlannedSession, **kwargs: object) -> PlannedSessionStep:
        step = PlannedSessionStep(planned_session_id=session.id, **kwargs)
        self.db.add(step)
        self.db.commit()
        self.db.refresh(step)
        return step

    def _create_activity_match(
        self,
        session: PlannedSession,
        activity_name: str,
        start_time: datetime,
        duration_sec: int,
    ) -> GarminActivity:
        activity = GarminActivity(
            athlete_id=session.athlete_id,
            garmin_activity_id=100000 + session.id,
            activity_name=activity_name,
            sport_type=session.sport_type,
            start_time=start_time,
            duration_sec=duration_sec,
            distance_m=0,
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
