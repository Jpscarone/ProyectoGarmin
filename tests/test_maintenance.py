from __future__ import annotations

from contextlib import ExitStack, contextmanager
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as app_main
from app.config import Settings
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
from app.services.local_db_sync_service import LocalDbSyncError, build_local_pre_sync_backup_filename, build_remote_backup_filename, sync_vps_to_local
from app.services.security import hash_password


class MaintenanceTests(unittest.TestCase):
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
        self._plan(self.athlete_one.id, "Plan Pablo")
        self.admin = self._user("admin@example.com", "Admin", "admin")
        self.coach = self._user("coach@example.com", "Coach", "coach")
        self._permission(self.coach.id, self.athlete_one.id, "coach", True, True, True)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app_main.SessionLocal = self.original_session_local
        self.db.close()
        self.engine.dispose()

    def test_admin_sees_configuracion_in_navbar(self) -> None:
        self._login_cookie(self.admin.id)

        response = self.client.get("/athletes/select", headers={"accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(">Configuracion<", response.text)
        self.assertNotIn(">Sync Garmin<", response.text)

    def test_non_admin_does_not_see_configuracion_in_navbar(self) -> None:
        self._login_cookie(self.coach.id)

        response = self.client.get("/athletes/select", headers={"accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(">Configuracion<", response.text)
        self.assertIn(">Sync Garmin<", response.text)

    def test_non_admin_cannot_access_maintenance_directly(self) -> None:
        self._login_cookie(self.coach.id)

        response = self.client.get("/configuracion")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_and_download_database_backup(self) -> None:
        self._login_cookie(self.admin.id)
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_dir = Path(temp_dir)

            def fake_run(command, **kwargs):
                output_path = Path(command[command.index("--file") + 1])
                output_path.write_text("-- backup --", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch("app.services.maintenance_service.BACKUP_DIR", backup_dir),
                patch("app.services.maintenance_service.shutil.which", return_value="pg_dump"),
                patch("app.services.maintenance_service.subprocess.run", side_effect=fake_run),
            ):
                response = self.client.post("/configuracion/database-backup", follow_redirects=False)

                self.assertEqual(response.status_code, 303)
                self.assertIn("/configuracion?status_message=", response.headers["location"])

                backup_files = list(backup_dir.glob("*.sql"))
                self.assertEqual(len(backup_files), 1)
                backup_name = backup_files[0].name
                self.assertRegex(
                    backup_name,
                    r"^\d{8}_\d{4}_ProyectoGarmin_training_app\.sql$",
                )

                maintenance_page = self.client.get("/configuracion")
                self.assertEqual(maintenance_page.status_code, 200)
                self.assertIn(backup_name, maintenance_page.text)

                download_response = self.client.get(f"/configuracion/database-backup/download/{backup_name}")
                self.assertEqual(download_response.status_code, 200)
                self.assertIn("attachment;", download_response.headers.get("content-disposition", ""))
                self.assertEqual(download_response.content, b"-- backup --")

    def test_backup_route_shows_clear_error_when_pg_dump_missing(self) -> None:
        self._login_cookie(self.admin.id)
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("app.services.maintenance_service.BACKUP_DIR", Path(temp_dir)),
                patch("app.services.maintenance_service.shutil.which", return_value=None),
            ):
                response = self.client.post("/configuracion/database-backup", follow_redirects=False)

                self.assertEqual(response.status_code, 303)
                self.assertIn("pg_dump", response.headers["location"])

    def test_download_rejects_path_traversal(self) -> None:
        self._login_cookie(self.admin.id)
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.services.maintenance_service.BACKUP_DIR", Path(temp_dir)):
                response = self.client.get("/configuracion/database-backup/download/../secret.txt")

        self.assertEqual(response.status_code, 404)

    def test_admin_in_production_does_not_see_sync_button_and_endpoint_is_forbidden(self) -> None:
        self._login_cookie(self.admin.id)
        settings = self._settings(app_env="production", enable_local_db_sync=True)

        with self._patch_settings(settings):
            page = self.client.get("/configuracion")
            post = self.client.post("/configuracion/sync-db-from-vps")

        self.assertEqual(page.status_code, 200)
        self.assertNotIn("Traer BD desde VPS", page.text)
        self.assertEqual(post.status_code, 403)

    def test_admin_in_local_with_sync_disabled_does_not_see_button_and_endpoint_is_forbidden(self) -> None:
        self._login_cookie(self.admin.id)
        settings = self._settings(app_env="local", enable_local_db_sync=False)

        with self._patch_settings(settings):
            page = self.client.get("/configuracion")
            post = self.client.post("/configuracion/sync-db-from-vps")

        self.assertEqual(page.status_code, 200)
        self.assertNotIn("Traer BD desde VPS", page.text)
        self.assertEqual(post.status_code, 403)

    def test_admin_in_local_with_sync_enabled_sees_button(self) -> None:
        self._login_cookie(self.admin.id)
        settings = self._settings(app_env="local", enable_local_db_sync=True)

        with self._patch_settings(settings):
            page = self.client.get("/configuracion")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Traer BD desde VPS", page.text)

    def test_service_blocks_sync_if_database_url_is_not_localhost(self) -> None:
        settings = self._settings(
            app_env="local",
            enable_local_db_sync=True,
            database_url="postgresql://training_user:secret@db.example.com/training_app",
        )

        with self.assertRaises(LocalDbSyncError) as context:
            sync_vps_to_local(settings=settings)

        self.assertEqual(context.exception.step, "configuración")
        self.assertIn("localhost", context.exception.message)

    def test_local_db_sync_builds_expected_filenames(self) -> None:
        settings = self._settings(app_env="local", enable_local_db_sync=True)

        remote_name = build_remote_backup_filename(settings)
        local_name = build_local_pre_sync_backup_filename(settings)

        self.assertRegex(remote_name, r"^\d{8}_\d{4}_ProyectoGarmin_VPS_training_app\.sql$")
        self.assertRegex(local_name, r"^\d{8}_\d{4}_ProyectoGarmin_LOCAL_pre_sync_training_app\.sql$")

    def test_sync_endpoint_runs_mocked_flow_successfully(self) -> None:
        self._login_cookie(self.admin.id)
        settings = self._settings(app_env="local", enable_local_db_sync=True)
        commands: list[list[str]] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            backup_dir = Path(temp_dir)

            def fake_which(tool_name: str) -> str:
                return tool_name

            def fake_run(command, **kwargs):
                commands.append(list(command))
                executable = command[0]
                if executable == "scp":
                    Path(command[-1]).write_text("-- downloaded backup --", encoding="utf-8")
                elif executable == "pg_dump":
                    output_path = Path(command[command.index("--file") + 1])
                    output_path.write_text("-- local backup --", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                self._patch_settings(settings),
                patch("app.services.local_db_sync_service.BACKUP_DIR", backup_dir, create=True),
                patch("app.services.maintenance_service.BACKUP_DIR", backup_dir),
                patch("app.services.local_db_sync_service.shutil.which", side_effect=fake_which),
                patch("app.services.local_db_sync_service.subprocess.run", side_effect=fake_run),
            ):
                response = self.client.post("/configuracion/sync-db-from-vps", follow_redirects=False)

                self.assertEqual(response.status_code, 303)
                self.assertIn("Base%20local%20actualizada%20con%20datos%20del%20VPS", response.headers["location"])
                self.assertIn("remote_backup=", response.headers["location"])
                self.assertIn("local_backup=", response.headers["location"])

                files = sorted(path.name for path in backup_dir.glob("*.sql"))
                self.assertEqual(len(files), 2)
                self.assertTrue(any(name.endswith("_VPS_training_app.sql") for name in files))
                self.assertTrue(any(name.endswith("_LOCAL_pre_sync_training_app.sql") for name in files))

        self.assertTrue(any(command[0] == "ssh" and "pg_dump" in command for command in commands))
        self.assertTrue(any(command[0] == "scp" for command in commands))
        self.assertTrue(any(command[0] == "pg_dump" for command in commands))
        self.assertTrue(any(command[0] == "psql" for command in commands))
        self.assertTrue(any(command[:4] == [sys.executable, "-m", "alembic", "upgrade"] for command in commands))

    def test_legacy_maintenance_url_redirects_to_configuracion(self) -> None:
        self._login_cookie(self.admin.id)

        response = self.client.get("/maintenance", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/configuracion")

    def _patch_settings(self, settings: Settings):
        @contextmanager
        def manager():
            with ExitStack() as stack:
                stack.enter_context(patch("app.routers.maintenance.get_settings", return_value=settings))
                stack.enter_context(patch("app.services.local_db_sync_service.get_settings", return_value=settings))
                stack.enter_context(patch("app.services.maintenance_service.get_settings", return_value=settings))
                yield

        return manager()

    def _settings(self, **overrides) -> Settings:
        defaults = {
            "app_name": "training_app",
            "app_env": "production",
            "debug": True,
            "enable_local_db_sync": False,
            "database_url": "postgresql://training_user:secret@localhost/training_app",
            "app_timezone": "America/Argentina/Buenos_Aires",
            "vps_sync_host": "vps.example.com",
            "vps_sync_user": "pablo",
            "vps_sync_ssh_port": 22,
            "vps_sync_remote_db_name": "training_app",
            "vps_sync_remote_db_user": "training_user",
            "vps_sync_remote_db_password": None,
            "vps_sync_remote_backup_dir": "/home/pablo",
            "local_db_name": "training_app",
            "local_db_user": "training_user",
            "local_db_password": None,
            "local_admin_db_user": "postgres",
            "local_admin_db_password": None,
            "project_backup_prefix": "ProyectoGarmin",
        }
        defaults.update(overrides)
        return Settings(**defaults)

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
