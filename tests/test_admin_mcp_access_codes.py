from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as app_main
from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import athlete_access_code  # noqa: F401
from app.db.models import user  # noqa: F401
from app.db.models import user_athlete_permission  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.athlete_access_code import AthleteAccessCode
from app.db.models.user import User
from app.db.models.user_athlete_permission import UserAthletePermission
from app.db.session import get_db
from app.main import app
from app.services.security import hash_password


class AdminMcpAccessCodesTests(unittest.TestCase):
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
        self.client = TestClient(app, raise_server_exceptions=False)

        self.athlete_one = self._athlete("Carolina")
        self.athlete_two = self._athlete("Lucia")
        self.admin = self._user("admin@example.com", "Admin", "admin")
        self.coach = self._user("coach@example.com", "Coach", "coach")
        self.athlete_user = self._user("athlete@example.com", "Athlete", "athlete")
        self._permission(self.coach.id, self.athlete_one.id, "coach", True, True, True)
        self._permission(self.athlete_user.id, self.athlete_one.id, "owner", True, True, True)
        self.code_one = self._access_code(self.athlete_one.id, "CARO-1234-ABCD", label="Carolina ChatGPT")
        self.code_two = self._access_code(self.athlete_two.id, "LUCI-5678-EFGH", label="Lucia ChatGPT")

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app_main.SessionLocal = self.original_session_local
        self.db.close()
        self.engine.dispose()

    def test_anonymous_user_is_redirected_from_admin_mcp_access_codes(self) -> None:
        response = self.client.get("/admin/mcp-access-codes", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?next=/admin/mcp-access-codes")

    def test_athlete_user_cannot_access_admin_mcp_access_codes(self) -> None:
        self._login_cookie(self.athlete_user.id)

        response = self.client.get("/admin/mcp-access-codes")

        self.assertEqual(response.status_code, 403)

    def test_coach_sees_only_manageable_athlete_codes(self) -> None:
        self._login_cookie(self.coach.id)

        response = self.client.get("/admin/mcp-access-codes")

        self.assertEqual(response.status_code, 200)
        self.assertIn("CARO-1234-ABCD", response.text)
        self.assertNotIn("LUCI-5678-EFGH", response.text)
        self.assertIn("Carolina", response.text)
        self.assertNotIn("Lucia ChatGPT", response.text)

    def test_admin_can_create_access_code_from_web(self) -> None:
        self._login_cookie(self.admin.id)

        response = self.client.post(
            "/admin/mcp-access-codes/create",
            data={
                "athlete_id": str(self.athlete_two.id),
                "prefix": "LUCI",
                "label": "Lucia ChatGPT 2",
                "notes": "Clave experimental",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        created = self.db.scalar(
            select(AthleteAccessCode)
            .where(
                AthleteAccessCode.athlete_id == self.athlete_two.id,
                AthleteAccessCode.label == "Lucia ChatGPT 2",
            )
            .order_by(AthleteAccessCode.id.desc())
        )
        self.assertIsNotNone(created)
        assert created is not None
        self.assertTrue(created.access_code.startswith("LUCI-"))
        self.assertEqual(created.notes, "Clave experimental")
        self.assertIn("created_code=", response.headers["location"])

    def test_admin_can_deactivate_and_reactivate_access_code(self) -> None:
        self._login_cookie(self.admin.id)

        deactivate_response = self.client.post(
            f"/admin/mcp-access-codes/{self.code_one.id}/deactivate",
            follow_redirects=False,
        )
        self.db.refresh(self.code_one)
        self.assertEqual(deactivate_response.status_code, 303)
        self.assertFalse(self.code_one.is_active)

        activate_response = self.client.post(
            f"/admin/mcp-access-codes/{self.code_one.id}/activate",
            follow_redirects=False,
        )
        self.db.refresh(self.code_one)
        self.assertEqual(activate_response.status_code, 303)
        self.assertTrue(self.code_one.is_active)

    def _login_cookie(self, user_id: int) -> None:
        self.client.cookies.set("training_app_context", f"current_user_id:{user_id}")

    def _athlete(self, name: str) -> Athlete:
        athlete = Athlete(name=name, status="active")
        self.db.add(athlete)
        self.db.commit()
        self.db.refresh(athlete)
        return athlete

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

    def _permission(
        self,
        user_id: int,
        athlete_id: int,
        permission_role: str,
        can_view: bool,
        can_edit: bool,
        can_sync_garmin: bool,
    ) -> None:
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

    def _access_code(self, athlete_id: int, access_code: str, label: str | None = None) -> AthleteAccessCode:
        row = AthleteAccessCode(
            athlete_id=athlete_id,
            access_code=access_code,
            label=label,
            is_active=True,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row


if __name__ == "__main__":
    unittest.main()
