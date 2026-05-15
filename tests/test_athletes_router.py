from __future__ import annotations

import unittest
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as app_main
from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import user  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.training_plan import TrainingPlan
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.services.security import hash_password


class AthletesRouterTests(unittest.TestCase):
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

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        admin = User(
            email="admin@example.com",
            name="Admin",
            password_hash=hash_password("secret123"),
            role="admin",
            is_active=True,
        )
        self.db.add(admin)
        self.db.commit()
        self.db.refresh(admin)
        self.client.cookies.set("training_app_context", f"current_user_id:{admin.id}")

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app_main.SessionLocal = self.original_session_local
        self.db.close()
        self.engine.dispose()

    def test_select_athlete_redirects_to_dashboard_with_default_plan(self) -> None:
        athlete = Athlete(name="Pablo")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        plan = TrainingPlan(
            athlete_id=athlete.id,
            name="Plan Base",
            sport_type="running",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 6, 20),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)

        response = self.client.post(
            "/athletes/select",
            data={"athlete_id": athlete.id},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"/dashboard?athlete_id={athlete.id}&training_plan_id={plan.id}")

    def test_select_athlete_without_plan_redirects_to_dashboard(self) -> None:
        athlete = Athlete(name="Pablo")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)

        response = self.client.post(
            "/athletes/select",
            data={"athlete_id": athlete.id},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"/dashboard?athlete_id={athlete.id}")


if __name__ == "__main__":
    unittest.main()
