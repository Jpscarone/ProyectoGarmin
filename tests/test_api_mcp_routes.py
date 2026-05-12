from __future__ import annotations

import os
import unittest
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db.models import activity_session_match  # noqa: F401
from app.db.models import athlete  # noqa: F401
from app.db.models import daily_health_metric  # noqa: F401
from app.db.models import garmin_activity  # noqa: F401
from app.db.models import goal  # noqa: F401
from app.db.models import health_ai_analysis  # noqa: F401
from app.db.models import planned_session  # noqa: F401
from app.db.models import session_analysis  # noqa: F401
from app.db.models import training_day  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import weekly_analysis  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.garmin_activity import GarminActivity
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
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
            "/api/mcp/session-feedback?date=2026-05-05",
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

    def test_week_context_returns_schema_version(self) -> None:
        response = self.client.get("/api/mcp/week-context", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "mcp_week_context_v1")

    def test_last_activity_feedback_does_not_break_without_activity(self) -> None:
        response = self.client.get("/api/mcp/last-activity-feedback", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "mcp_last_activity_feedback_v1")
        self.assertIsNone(payload["completed_activity"])
        self.assertIsNone(payload["analysis"])

    def test_next_session_context_does_not_break_without_next_session(self) -> None:
        response = self.client.get("/api/mcp/next-session-context", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "mcp_next_session_context_v1")
        self.assertIsNone(payload["next_session"])
