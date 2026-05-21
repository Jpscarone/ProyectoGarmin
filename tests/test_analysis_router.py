from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import app.main as app_main
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import user  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.services.security import hash_password


class AnalysisRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.middleware_session_local = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.original_session_local = app_main.SessionLocal
        app_main.SessionLocal = self.middleware_session_local

        athlete_row = Athlete(name="Atleta Analisis")
        self.db.add(athlete_row)
        self.db.commit()
        self.db.refresh(athlete_row)
        self.athlete = athlete_row

        admin = User(
            email="admin-analysis@example.com",
            name="Admin Analysis",
            password_hash=hash_password("secret123"),
            role="admin",
            is_active=True,
        )
        self.db.add(admin)
        self.db.commit()
        self.db.refresh(admin)
        self.admin = admin

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.client.cookies.set("training_app_context", f"current_user_id:{self.admin.id}")

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app_main.SessionLocal = self.original_session_local
        self.db.close()
        self.engine.dispose()

    @patch("app.routers.analysis.re_run_weekly_analysis")
    def test_rerun_weekly_analysis_post_redirects_without_server_error(self, rerun_mock) -> None:
        rerun_mock.return_value = SimpleNamespace(status="completed")

        response = self.client.post(
            f"/analysis/weekly/{self.athlete.id}/{date(2026, 5, 11).isoformat()}/re-run",
            data={
                "return_to": "calendar",
                "plan_id": "2",
                "month": "2026-05",
                "selected_date": "2026-05-11",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn(f"/analysis/weekly/{self.athlete.id}/2026-05-11", response.headers["location"])
        self.assertIn("return_to=calendar", response.headers["location"])
        self.assertIn("plan_id=2", response.headers["location"])
        self.assertIn("selected_date=2026-05-11", response.headers["location"])
        rerun_mock.assert_called_once()

