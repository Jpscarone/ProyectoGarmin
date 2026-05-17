from __future__ import annotations

import unittest
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as app_main
from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.models import training_plan  # noqa: F401
from app.db.models import user  # noqa: F401
from app.db.models import user_athlete_permission  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.training_plan import TrainingPlan
from app.db.models.user import User
from app.db.models.user_athlete_permission import UserAthletePermission
from app.db.session import get_db
from app.main import app
from app.services.security import hash_password, verify_password


class AdminUsersTests(unittest.TestCase):
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

        self.athlete_one = self._athlete("Pablo")
        self.athlete_two = self._athlete("Lucia")
        self._plan(self.athlete_one.id, "Plan Pablo")
        self._plan(self.athlete_two.id, "Plan Lucia")
        self.admin = self._user("admin@example.com", "Admin", "admin")
        self.coach = self._user("coach@example.com", "Coach", "coach")
        self.athlete_user = self._user("athlete@example.com", "Athlete", "athlete")
        self._permission(self.coach.id, self.athlete_one.id, "coach", True, True, True)
        self._permission(self.athlete_user.id, self.athlete_one.id, "owner", True, True, True)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app_main.SessionLocal = self.original_session_local
        self.db.close()
        self.engine.dispose()

    def test_anonymous_user_is_redirected_from_admin_users(self) -> None:
        response = self.client.get("/admin/users", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?next=/admin/users")

    def test_athlete_user_cannot_access_admin_users(self) -> None:
        self._login_cookie(self.athlete_user.id)

        response = self.client.get("/admin/users")

        self.assertEqual(response.status_code, 403)

    def test_coach_user_cannot_access_admin_users(self) -> None:
        self._login_cookie(self.coach.id)

        response = self.client.get("/admin/users")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_admin_users(self) -> None:
        self._login_cookie(self.admin.id)

        response = self.client.get("/admin/users")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Usuarios", response.text)

    def test_admin_can_create_athlete_user_assigned_to_one_athlete(self) -> None:
        self._login_cookie(self.admin.id)

        response = self.client.post(
            "/admin/users/new",
            data={
                "email": "nuevo@example.com",
                "name": "Nuevo atleta",
                "password": "clave-inicial",
                "role": "athlete",
                "is_active": "true",
                "athlete_id": str(self.athlete_two.id),
                "permission_role": "owner",
                "can_view": "on",
                "can_edit": "on",
                "can_sync_garmin": "on",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        created_user = self.db.scalar(select(User).where(User.email == "nuevo@example.com"))
        self.assertIsNotNone(created_user)
        assert created_user is not None
        self.assertNotEqual(created_user.password_hash, "clave-inicial")
        self.assertTrue(verify_password("clave-inicial", created_user.password_hash))

        permission = self.db.scalar(select(UserAthletePermission).where(UserAthletePermission.user_id == created_user.id))
        self.assertIsNotNone(permission)
        assert permission is not None
        self.assertEqual(permission.athlete_id, self.athlete_two.id)
        self.assertEqual(permission.permission_role, "owner")

    def test_created_user_can_login_and_only_sees_assigned_athlete(self) -> None:
        self._login_cookie(self.admin.id)
        self.client.post(
            "/admin/users/new",
            data={
                "email": "solo@example.com",
                "name": "Solo atleta",
                "password": "clave-inicial",
                "role": "athlete",
                "is_active": "true",
                "athlete_id": str(self.athlete_two.id),
                "permission_role": "owner",
                "can_view": "on",
                "can_edit": "on",
                "can_sync_garmin": "on",
            },
            follow_redirects=False,
        )
        self.client.cookies.clear()

        login_response = self.client.post(
            "/login",
            data={"email": "solo@example.com", "password": "clave-inicial"},
            follow_redirects=False,
        )
        select_response = self.client.get("/athletes/select", headers={"accept": "text/html"})

        self.assertEqual(login_response.status_code, 303)
        self.assertIn(f"athlete_id={self.athlete_two.id}", login_response.headers["location"])
        self.assertEqual(select_response.status_code, 200)
        self.assertIn("Lucia", select_response.text)
        self.assertNotIn("Pablo", select_response.text)

    def test_admin_can_reset_password_without_seeing_previous_password(self) -> None:
        self._login_cookie(self.admin.id)
        managed_user = self._user("reset@example.com", "Reset User", "athlete")
        old_hash = managed_user.password_hash

        response = self.client.post(
            f"/admin/users/{managed_user.id}/reset-password",
            data={"new_password": "nueva-clave", "confirm_password": "nueva-clave"},
            follow_redirects=False,
        )
        self.db.refresh(managed_user)
        self.client.cookies.clear()

        old_login = self.client.post(
            "/login",
            data={"email": managed_user.email, "password": "secret123"},
            follow_redirects=False,
        )
        new_login = self.client.post(
            "/login",
            data={"email": managed_user.email, "password": "nueva-clave"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertNotEqual(managed_user.password_hash, old_hash)
        self.assertTrue(verify_password("nueva-clave", managed_user.password_hash))
        self.assertEqual(old_login.headers["location"], "/login?error=Credenciales%20inv%C3%A1lidas")
        self.assertEqual(new_login.status_code, 303)

    def test_admin_can_activate_and_deactivate_user(self) -> None:
        self._login_cookie(self.admin.id)
        managed_user = self._user("toggle@example.com", "Toggle User", "athlete")

        deactivate_response = self.client.post(f"/admin/users/{managed_user.id}/deactivate", follow_redirects=False)
        self.db.refresh(managed_user)
        self.assertEqual(deactivate_response.status_code, 303)
        self.assertFalse(managed_user.is_active)
        inactive_login = self.client.post(
            "/login",
            data={"email": managed_user.email, "password": "secret123"},
            follow_redirects=False,
        )
        activate_response = self.client.post(f"/admin/users/{managed_user.id}/activate", follow_redirects=False)
        self.db.refresh(managed_user)
        active_login = self.client.post(
            "/login",
            data={"email": managed_user.email, "password": "secret123"},
            follow_redirects=False,
        )

        self.assertEqual(inactive_login.headers["location"], "/login?error=Credenciales%20inv%C3%A1lidas")
        self.assertEqual(activate_response.status_code, 303)
        self.assertTrue(managed_user.is_active)
        self.assertEqual(active_login.status_code, 303)

    def test_admin_can_add_edit_and_delete_athlete_permission(self) -> None:
        self._login_cookie(self.admin.id)
        managed_user = self._user("perm@example.com", "Perm User", "coach")

        add_response = self.client.post(
            f"/admin/users/{managed_user.id}/permissions/add",
            data={
                "athlete_id": str(self.athlete_one.id),
                "permission_role": "viewer",
                "can_view": "on",
            },
            follow_redirects=False,
        )
        permission = self.db.scalar(select(UserAthletePermission).where(UserAthletePermission.user_id == managed_user.id))
        assert permission is not None

        edit_response = self.client.post(
            f"/admin/users/{managed_user.id}/permissions/{permission.id}/edit",
            data={
                "permission_role": "coach",
                "can_view": "on",
                "can_edit": "on",
                "can_sync_garmin": "on",
            },
            follow_redirects=False,
        )
        self.db.refresh(permission)

        delete_response = self.client.post(
            f"/admin/users/{managed_user.id}/permissions/{permission.id}/delete",
            follow_redirects=False,
        )
        deleted_permission = self.db.get(UserAthletePermission, permission.id)

        self.assertEqual(add_response.status_code, 303)
        self.assertEqual(permission.permission_role, "coach")
        self.assertTrue(permission.can_edit)
        self.assertTrue(permission.can_sync_garmin)
        self.assertEqual(edit_response.status_code, 303)
        self.assertEqual(delete_response.status_code, 303)
        self.assertIsNone(deleted_permission)

    def test_duplicate_email_is_rejected(self) -> None:
        self._login_cookie(self.admin.id)

        response = self.client.post(
            "/admin/users/new",
            data={
                "email": self.coach.email,
                "name": "Duplicado",
                "password": "clave-inicial",
                "role": "athlete",
                "is_active": "true",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("/admin/users/new?error=", response.headers["location"])
        users = list(self.db.scalars(select(User).where(User.email == self.coach.email)).all())
        self.assertEqual(len(users), 1)

    def test_duplicate_permission_for_same_user_and_athlete_is_rejected(self) -> None:
        self._login_cookie(self.admin.id)
        managed_user = self._user("dupperm@example.com", "Dup Perm", "coach")
        self._permission(managed_user.id, self.athlete_one.id, "viewer", True, False, False)

        response = self.client.post(
            f"/admin/users/{managed_user.id}/permissions/add",
            data={
                "athlete_id": str(self.athlete_one.id),
                "permission_role": "coach",
                "can_view": "on",
                "can_edit": "on",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn(f"/admin/users/{managed_user.id}/edit?error=", response.headers["location"])
        permissions = list(self.db.scalars(select(UserAthletePermission).where(UserAthletePermission.user_id == managed_user.id)).all())
        self.assertEqual(len(permissions), 1)

    def _login_cookie(self, user_id: int) -> None:
        self.client.cookies.set("training_app_context", f"current_user_id:{user_id}")

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


if __name__ == "__main__":
    unittest.main()
