from __future__ import annotations

import os
import unittest
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
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
from app.db.models.athlete import Athlete
from app.db.models.athlete_access_code import AthleteAccessCode
from app.db.models.weekly_analysis import WeeklyAnalysis
from app.db.session import get_db
from app.main import app


class WeekMetricsJsonPayloadTests(unittest.TestCase):
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

        self.athlete = Athlete(name="Atleta Weekly RAW")
        self.db.add(self.athlete)
        self.db.commit()
        self.db.refresh(self.athlete)
        self.db.add(
            AthleteAccessCode(
                athlete_id=self.athlete.id,
                access_code="WEEK-RAW-1234",
                label="Weekly raw",
                is_active=True,
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

    def _create_weekly_analysis(
        self,
        *,
        week_start_date: date,
        week_end_date: date,
        metrics_json: dict | None,
    ) -> WeeklyAnalysis:
        row = WeeklyAnalysis(
            athlete_id=self.athlete.id,
            week_start_date=week_start_date,
            week_end_date=week_end_date,
            status="completed",
            analysis_version="v2",
            metrics_json=metrics_json,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def test_returns_latest_available_week_with_metrics_json(self) -> None:
        self._create_weekly_analysis(
            week_start_date=date(2026, 5, 12),
            week_end_date=date(2026, 5, 18),
            metrics_json={"totals": {"sessions": 3}},
        )
        latest = self._create_weekly_analysis(
            week_start_date=date(2026, 5, 19),
            week_end_date=date(2026, 5, 25),
            metrics_json={"totals": {"sessions": 5}, "scores": {"load": 81}},
        )

        response = self.client.get(
            f"/api/mcp/week-metrics-json?athlete_id={self.athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["metrics_json_available"])
        self.assertEqual(payload["week"]["week_start_date"], latest.week_start_date.isoformat())
        self.assertEqual(payload["metrics_json"]["totals"]["sessions"], 5)

    def test_resolves_specific_week_start_date(self) -> None:
        self._create_weekly_analysis(
            week_start_date=date(2026, 5, 19),
            week_end_date=date(2026, 5, 25),
            metrics_json={"totals": {"sessions": 5}},
        )

        response = self.client.get(
            f"/api/mcp/week-metrics-json?athlete_id={self.athlete.id}&week_start_date=2026-05-19",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["week"]["week_start_date"], "2026-05-19")

    def test_resolves_reference_date(self) -> None:
        self._create_weekly_analysis(
            week_start_date=date(2026, 5, 19),
            week_end_date=date(2026, 5, 25),
            metrics_json={"trends": {"load_direction": "up"}},
        )

        response = self.client.get(
            f"/api/mcp/week-metrics-json?athlete_id={self.athlete.id}&reference_date=2026-05-21",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["week"]["week_start_date"], "2026-05-19")
        self.assertEqual(payload["metrics_json"]["trends"]["load_direction"], "up")

    def test_returns_false_when_week_exists_without_metrics_json(self) -> None:
        self._create_weekly_analysis(
            week_start_date=date(2026, 5, 19),
            week_end_date=date(2026, 5, 25),
            metrics_json=None,
        )

        response = self.client.get(
            f"/api/mcp/week-metrics-json?athlete_id={self.athlete.id}&week_start_date=2026-05-19",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["metrics_json_available"])
        self.assertIsNone(payload["metrics_json"])
        self.assertIn("No hay weekly metrics_json disponible.", payload["limitations"])

    def test_returns_false_when_no_metrics_json_exists_anywhere(self) -> None:
        response = self.client.get(
            f"/api/mcp/week-metrics-json?athlete_id={self.athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["metrics_json_available"])
        self.assertIsNone(payload["metrics_json"])
        self.assertIn("No hay weekly metrics_json disponible.", payload["limitations"])

    def test_conflicting_start_and_end_returns_409(self) -> None:
        self._create_weekly_analysis(
            week_start_date=date(2026, 5, 19),
            week_end_date=date(2026, 5, 25),
            metrics_json={"totals": {"sessions": 1}},
        )

        response = self.client.get(
            f"/api/mcp/week-metrics-json?athlete_id={self.athlete.id}&week_start_date=2026-05-19&week_end_date=2026-05-26",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 409)

    def test_wrapper_access_code_works(self) -> None:
        self._create_weekly_analysis(
            week_start_date=date(2026, 5, 19),
            week_end_date=date(2026, 5, 25),
            metrics_json={"scores": {"fatigue": 44}},
        )

        response = self.client.get(
            "/api/mcp/my/week-metrics-json?access_code=WEEK-RAW-1234&week_start_date=2026-05-19",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete"]["id"], self.athlete.id)
        self.assertEqual(payload["metrics_json"]["scores"]["fatigue"], 44)

    def test_endpoint_does_not_modify_db(self) -> None:
        self._create_weekly_analysis(
            week_start_date=date(2026, 5, 19),
            week_end_date=date(2026, 5, 25),
            metrics_json={"totals": {"sessions": 2}},
        )
        before = self.db.scalar(select(func.count()).select_from(WeeklyAnalysis))

        response = self.client.get(
            f"/api/mcp/week-metrics-json?athlete_id={self.athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        after = self.db.scalar(select(func.count()).select_from(WeeklyAnalysis))
        self.assertEqual(before, after)

    def test_returns_totals_trends_and_scores_complete(self) -> None:
        self._create_weekly_analysis(
            week_start_date=date(2026, 5, 19),
            week_end_date=date(2026, 5, 25),
            metrics_json={
                "totals": {"duration_sec": 14400},
                "trends": {"delta_duration_pct": 12.5},
                "scores": {"consistency": 77},
            },
        )

        response = self.client.get(
            f"/api/mcp/week-metrics-json?athlete_id={self.athlete.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["metrics_json"]["totals"]["duration_sec"], 14400)
        self.assertEqual(payload["metrics_json"]["trends"]["delta_duration_pct"], 12.5)
        self.assertEqual(payload["metrics_json"]["scores"]["consistency"], 77)


if __name__ == "__main__":
    unittest.main()
