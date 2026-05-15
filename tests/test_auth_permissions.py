from __future__ import annotations

import unittest
from datetime import date

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as app_main
from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import garmin_account  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import user  # noqa: F401
from app.db.models import user_athlete_permission  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.garmin_account import GarminAccount
from app.db.models.training_plan import TrainingPlan
from app.db.models.user import User
from app.db.models.user_athlete_permission import UserAthletePermission
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.services.garmin_credential_service import default_token_dir_for_athlete, get_or_create_garmin_account
from app.services.security import hash_password
from app.services.garmin_credential_service import decrypt_garmin_password


class AuthPermissionsTests(unittest.TestCase):
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
        self.settings = get_settings()
        self.original_garmin_secret_key = self.settings.garmin_credential_secret_key
        self.garmin_secret_key = Fernet.generate_key().decode("utf-8")
        self.settings.garmin_credential_secret_key = self.garmin_secret_key

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app, raise_server_exceptions=False)
        self.athlete_one = self._athlete("Pablo")
        self.athlete_two = self._athlete("Lucia")
        self.plan_one = self._plan(self.athlete_one.id, "Plan Pablo")
        self.plan_two = self._plan(self.athlete_two.id, "Plan Lucia")
        self.admin = self._user("admin@example.com", "Admin", "admin")
        self.coach = self._user("coach@example.com", "Coach", "coach")
        self.athlete_user = self._user("athlete@example.com", "Athlete", "athlete")
        self.viewer = self._user("viewer@example.com", "Viewer", "athlete")
        self._permission(self.coach.id, self.athlete_one.id, "coach", True, True, True)
        self._permission(self.athlete_user.id, self.athlete_one.id, "owner", True, True, True)
        self._permission(self.viewer.id, self.athlete_one.id, "viewer", True, False, False)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app_main.SessionLocal = self.original_session_local
        self.settings.garmin_credential_secret_key = self.original_garmin_secret_key
        self.db.close()
        self.engine.dispose()

    def test_login_success_sets_session_cookie(self) -> None:
        response = self.client.post(
            "/login",
            data={"email": "athlete@example.com", "password": "secret123"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("training_app_context=", response.headers.get("set-cookie", ""))
        self.assertIn("current_user_id", response.headers.get("set-cookie", ""))

    def test_login_failure_redirects_back_to_login(self) -> None:
        response = self.client.post(
            "/login",
            data={"email": "athlete@example.com", "password": "bad-pass"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?error=Credenciales%20inv%C3%A1lidas")

    def test_logout_clears_user_and_context(self) -> None:
        self.client.cookies.set(
            "training_app_context",
            f"current_user_id:{self.admin.id}|current_athlete_id:{self.athlete_one.id}|current_training_plan_id:{self.plan_one.id}",
        )

        response = self.client.post("/logout", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        set_cookie = response.headers.get("set-cookie", "")
        self.assertNotIn("current_user_id", set_cookie)
        self.assertNotIn("current_athlete_id", set_cookie)
        self.assertNotIn("current_training_plan_id", set_cookie)

    def test_athlete_user_sees_only_own_athlete(self) -> None:
        self._login_cookie(self.athlete_user.id)

        response = self.client.get("/athletes/select", headers={"accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Pablo", response.text)
        self.assertNotIn("Lucia", response.text)

    def test_coach_sees_only_assigned_athletes(self) -> None:
        self._login_cookie(self.coach.id)

        response = self.client.get("/athletes/select", headers={"accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Pablo", response.text)
        self.assertNotIn("Lucia", response.text)

    def test_admin_sees_all_athletes(self) -> None:
        self._login_cookie(self.admin.id)

        response = self.client.get("/athletes/select", headers={"accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Pablo", response.text)
        self.assertIn("Lucia", response.text)

    def test_cannot_select_unpermitted_athlete(self) -> None:
        self._login_cookie(self.athlete_user.id)

        response = self.client.post(
            "/athletes/select",
            data={"athlete_id": self.athlete_two.id},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 403)

    def test_training_plans_route_blocks_unpermitted_athlete(self) -> None:
        self._login_cookie(self.athlete_user.id)

        response = self.client.get(f"/training_plans?athlete_id={self.athlete_two.id}")

        self.assertEqual(response.status_code, 403)

    def test_edit_is_blocked_without_can_edit(self) -> None:
        self._login_cookie(self.viewer.id)

        response = self.client.put(
            f"/athletes/{self.athlete_one.id}",
            json={"name": "Nuevo nombre"},
        )

        self.assertEqual(response.status_code, 403)

    def test_garmin_sync_is_blocked_without_can_sync_permission(self) -> None:
        self._login_cookie(self.viewer.id, athlete_id=self.athlete_one.id)

        response = self.client.post(
            "/garmin/account",
            data={"garmin_email": "viewer@garmin.com", "garmin_password": "nope", "is_active": "on"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 403)

    def test_garmin_account_password_is_saved_encrypted(self) -> None:
        self._login_cookie(self.coach.id, athlete_id=self.athlete_one.id)

        response = self.client.post(
            "/garmin/account",
            data={"garmin_email": "pablo@garmin.com", "garmin_password": "garmin-secret", "is_active": "on"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        account = self.db.query(GarminAccount).filter(GarminAccount.athlete_id == self.athlete_one.id).one()
        self.assertNotEqual(account.garmin_password_encrypted, "garmin-secret")
        self.assertEqual(
            decrypt_garmin_password(account.garmin_password_encrypted, self.garmin_secret_key),
            "garmin-secret",
        )

    def test_garmin_token_dir_is_per_athlete(self) -> None:
        account_one = get_or_create_garmin_account(self.db, self.athlete_one)
        account_two = get_or_create_garmin_account(self.db, self.athlete_two)

        self.assertEqual(account_one.token_dir, default_token_dir_for_athlete(self.athlete_one.id))
        self.assertEqual(account_two.token_dir, default_token_dir_for_athlete(self.athlete_two.id))
        self.assertNotEqual(account_one.token_dir, account_two.token_dir)

    def test_dashboard_redirects_to_login_without_session(self) -> None:
        response = self.client.get("/dashboard", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?next=/dashboard")

    def _login_cookie(self, user_id: int, athlete_id: int | None = None) -> None:
        parts = [f"current_user_id:{user_id}"]
        if athlete_id is not None:
            parts.append(f"current_athlete_id:{athlete_id}")
        self.client.cookies.set("training_app_context", "|".join(parts))

    def _athlete(self, name: str) -> Athlete:
        athlete = Athlete(name=name, status="active")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        return athlete

    def _plan(self, athlete_id: int, name: str) -> TrainingPlan:
        plan = TrainingPlan(
            athlete_id=athlete_id,
            name=name,
            sport_type="running",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 6, 1),
            status="active",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _user(self, email: str, name: str, role: str) -> User:
        user = User(
            email=email,
            name=name,
            password_hash=hash_password("secret123"),
            role=role,
            is_active=True,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def _permission(self, user_id: int, athlete_id: int, permission_role: str, can_view: bool, can_edit: bool, can_sync_garmin: bool) -> None:
        row = UserAthletePermission(
            user_id=user_id,
            athlete_id=athlete_id,
            permission_role=permission_role,
            can_view=can_view,
            can_edit=can_edit,
            can_sync_garmin=can_sync_garmin,
        )
        self.db.add(row)
        self.db.commit()


if __name__ == "__main__":
    unittest.main()
