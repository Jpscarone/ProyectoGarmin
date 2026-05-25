from __future__ import annotations

import os
import unittest
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db import models  # noqa: F401
from app.db.models.athlete import Athlete
from app.db.models.planned_session import PlannedSession
from app.db.models.training_day import TrainingDay
from app.db.models.training_plan import TrainingPlan
from app.db.session import get_db
from app.main import app
from app.services.plan_import_parser import parse_plan_import
from app.services.plan_import_service import commit_plan_import, preview_plan_import


WEEK_TEXT = """WEEK
ATHLETE_ID: 1
ATHLETE_NAME: Pablo
START_DATE: 2026-05-25
END_DATE: 2026-05-31
MODE: preview

SESSION
ACTION: upsert
DATE: 2026-05-26
SPORT: strength
MODALITY: indoor
NAME: Gimnasio suave
NOTES: mantenimiento y movilidad sin fatigar piernas

BLOCK
VALUE: 45
UNIT: min
INTENSITY: rpe
ZONE: custom
RPE_MIN: 3
RPE_MAX: 5

SESSION
ACTION: cancel
DATE: 2026-05-27
SPORT: running
REASON: fatiga alta

END
"""


class PlanImportParserTests(unittest.TestCase):
    def test_parser_week_with_two_sessions(self) -> None:
        payload = parse_plan_import(WEEK_TEXT)

        self.assertEqual(payload.start_date, date(2026, 5, 25))
        self.assertEqual(payload.athlete_id, 1)
        self.assertEqual(payload.athlete_name, "Pablo")
        self.assertEqual(payload.end_date, date(2026, 5, 31))
        self.assertEqual(payload.mode, "preview")
        self.assertEqual(len(payload.sessions), 2)
        self.assertEqual(payload.sessions[0].action, "upsert")
        self.assertEqual(payload.sessions[0].blocks[0].value, 45)
        self.assertEqual(payload.sessions[1].action, "cancel")
        self.assertEqual(payload.sessions[1].reason, "fatiga alta")

    def test_parser_with_athlete_id(self) -> None:
        payload = parse_plan_import(
            """WEEK
ATHLETE_ID: 7

SESSION
ACTION: create
DATE: 2026-05-26
SPORT: running
NAME: Rodaje

BLOCK
VALUE: 30
UNIT: min

END
"""
        )

        self.assertEqual(payload.athlete_id, 7)
        self.assertIsNone(payload.athlete_name)

    def test_parser_with_athlete_id_and_name(self) -> None:
        payload = parse_plan_import(
            """WEEK
ATHLETE_ID: 7
ATHLETE_NAME: Pablo

SESSION
ACTION: cancel
DATE: 2026-05-26
SPORT: running

END
"""
        )

        self.assertEqual(payload.athlete_id, 7)
        self.assertEqual(payload.athlete_name, "Pablo")

    def test_parser_single_session_without_week(self) -> None:
        payload = parse_plan_import(
            """SESSION
ACTION: create
DATE: 2026-05-26
SPORT: running
NAME: Rodaje suave

BLOCK
VALUE: 30
UNIT: min

END
"""
        )

        self.assertIsNone(payload.start_date)
        self.assertEqual(len(payload.sessions), 1)
        self.assertEqual(payload.sessions[0].name, "Rodaje suave")

    def test_parser_cancel(self) -> None:
        payload = parse_plan_import(
            """SESSION
ACTION: cancel
SESSION_ID: 10
REASON: viaje
END
"""
        )

        self.assertEqual(payload.sessions[0].action, "cancel")
        self.assertEqual(payload.sessions[0].session_id, 10)
        self.assertEqual(payload.sessions[0].reason, "viaje")


class PlanImportServiceAndRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_read_token = os.environ.get("MCP_API_TOKEN")
        self.previous_write_token = os.environ.get("MCP_WRITE_API_TOKEN")
        os.environ["MCP_API_TOKEN"] = "read-token"
        os.environ["MCP_WRITE_API_TOKEN"] = "write-token"
        get_settings.cache_clear()

        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.athlete = Athlete(name="Atleta Plan Import")
        self.db.add(self.athlete)
        self.db.commit()
        self.db.refresh(self.athlete)
        self.other_athlete = Athlete(name="Otro Atleta")
        self.db.add(self.other_athlete)
        self.db.commit()
        self.db.refresh(self.other_athlete)
        self.plan = TrainingPlan(
            athlete_id=self.athlete.id,
            name="Plan Import",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add(self.plan)
        self.db.commit()
        self.db.refresh(self.plan)

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self.previous_read_token is None:
            os.environ.pop("MCP_API_TOKEN", None)
        else:
            os.environ["MCP_API_TOKEN"] = self.previous_read_token
        if self.previous_write_token is None:
            os.environ.pop("MCP_WRITE_API_TOKEN", None)
        else:
            os.environ["MCP_WRITE_API_TOKEN"] = self.previous_write_token
        get_settings.cache_clear()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_preview_create(self) -> None:
        payload = parse_plan_import(_create_text())

        result = preview_plan_import(self.db, self.athlete.id, payload)

        self.assertTrue(result["valid"])
        self.assertEqual(result["operations"][0]["operation"], "will_create")

    def test_preview_conflict_duplicate_create(self) -> None:
        self._add_session(date(2026, 5, 26), "running", "Existente")
        payload = parse_plan_import(_create_text())

        result = preview_plan_import(self.db, self.athlete.id, payload)

        self.assertFalse(result["valid"])
        self.assertEqual(result["operations"][0]["operation"], "conflict")

    def test_preview_update_not_found(self) -> None:
        payload = parse_plan_import(
            """SESSION
ACTION: update
DATE: 2026-05-26
SPORT: running
NAME: Rodaje editado
END
"""
        )

        result = preview_plan_import(self.db, self.athlete.id, payload)

        self.assertFalse(result["valid"])
        self.assertEqual(result["operations"][0]["operation"], "not_found")

    def test_commit_create(self) -> None:
        payload = parse_plan_import(_create_text())

        result = commit_plan_import(self.db, self.athlete.id, payload)

        self.assertEqual(result["created"], 1)
        session = self.db.scalar(select(PlannedSession).where(PlannedSession.athlete_id == self.athlete.id))
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.name, "Rodaje suave")
        self.assertEqual(session.expected_duration_min, 30)
        self.assertEqual(len(session.planned_session_steps), 1)

    def test_commit_upsert_update_existing(self) -> None:
        existing = self._add_session(date(2026, 5, 26), "running", "Viejo")
        payload = parse_plan_import(
            """SESSION
ACTION: upsert
DATE: 2026-05-26
SPORT: running
NAME: Nuevo

BLOCK
VALUE: 40
UNIT: min

END
"""
        )

        result = commit_plan_import(self.db, self.athlete.id, payload)
        self.db.refresh(existing)

        self.assertEqual(result["updated"], 1)
        self.assertEqual(existing.name, "Nuevo")
        self.assertEqual(existing.expected_duration_min, 40)
        self.assertEqual(len(existing.planned_session_steps), 1)

    def test_commit_cancel(self) -> None:
        existing = self._add_session(date(2026, 5, 27), "running", "Cancelar")
        payload = parse_plan_import(
            f"""SESSION
ACTION: cancel
SESSION_ID: {existing.id}
REASON: fatiga alta
END
"""
        )

        result = commit_plan_import(self.db, self.athlete.id, payload)
        self.db.refresh(existing)

        self.assertEqual(result["cancelled"], 1)
        self.assertEqual(existing.completion_source, "cancelled")
        self.assertIn("fatiga alta", existing.manual_completion_notes)

    def test_commit_endpoint_requires_confirmation_aplicar(self) -> None:
        response = self.client.post(
            "/api/mcp/plan-import/commit",
            headers={"Authorization": "Bearer write-token"},
            json={"import_text": _create_text(self.athlete.id), "confirmation": "NO"},
        )

        self.assertEqual(response.status_code, 400)

    def test_commit_endpoint_requires_write_token(self) -> None:
        response = self.client.post(
            "/api/mcp/plan-import/commit",
            headers={"Authorization": "Bearer read-token"},
            json={"import_text": _create_text(self.athlete.id), "confirmation": "APLICAR"},
        )

        self.assertEqual(response.status_code, 401)

    def test_preview_endpoint_uses_athlete_id_from_block(self) -> None:
        response = self.client.post(
            "/api/mcp/plan-import/preview",
            headers={"Authorization": "Bearer read-token"},
            json={"import_text": _create_text(self.other_athlete.id), "athlete_id": self.athlete.id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["athlete"]["id"], self.other_athlete.id)
        self.assertTrue(payload["valid"])

    def test_preview_endpoint_fails_without_athlete_id_when_multiple_athletes(self) -> None:
        response = self.client.post(
            "/api/mcp/plan-import/preview",
            headers={"Authorization": "Bearer read-token"},
            json={"import_text": _create_text()},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "El bloque importable debe incluir ATHLETE_ID en WEEK.")

    def test_commit_endpoint_uses_athlete_id_from_block(self) -> None:
        other_plan = TrainingPlan(
            athlete_id=self.other_athlete.id,
            name="Plan otro",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status="active",
        )
        self.db.add(other_plan)
        self.db.commit()

        response = self.client.post(
            "/api/mcp/plan-import/commit",
            headers={"Authorization": "Bearer write-token"},
            json={
                "import_text": _create_text(self.other_athlete.id),
                "athlete_id": self.athlete.id,
                "confirmation": "APLICAR",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["athlete"]["id"], self.other_athlete.id)
        session = self.db.scalar(select(PlannedSession).where(PlannedSession.athlete_id == self.other_athlete.id))
        self.assertIsNotNone(session)

    def test_preview_warns_if_athlete_name_mismatch(self) -> None:
        response = self.client.post(
            "/api/mcp/plan-import/preview",
            headers={"Authorization": "Bearer read-token"},
            json={"import_text": _create_text(self.athlete.id, athlete_name="Nombre incorrecto")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("ATHLETE_NAME no coincide", " ".join(response.json()["warnings"]))

    def test_rollback_if_one_operation_fails(self) -> None:
        payload = parse_plan_import(
            """SESSION
ACTION: create
DATE: 2026-05-26
SPORT: running
NAME: Primera

BLOCK
VALUE: 30
UNIT: min

SESSION
ACTION: create
DATE: 2026-05-27
SPORT: strength
NAME: Segunda

BLOCK
VALUE: 30
UNIT: min

END
"""
        )
        import app.services.plan_import_service as service

        original_create = service._create_session
        calls = {"count": 0}

        def failing_create(db, athlete_id, session_in):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("fallo simulado")
            return original_create(db, athlete_id, session_in)

        with patch("app.services.plan_import_service._create_session", side_effect=failing_create):
            result = commit_plan_import(self.db, self.athlete.id, payload)

        self.assertIn("fallo simulado", result["errors"][0])
        sessions = list(self.db.scalars(select(PlannedSession)).all())
        self.assertEqual(sessions, [])

    def _add_session(self, day: date, sport: str, name: str) -> PlannedSession:
        training_day = TrainingDay(
            athlete_id=self.athlete.id,
            training_plan_id=self.plan.id,
            day_date=day,
            day_type=sport,
        )
        self.db.add(training_day)
        self.db.commit()
        self.db.refresh(training_day)
        session = PlannedSession(
            athlete_id=self.athlete.id,
            training_day_id=training_day.id,
            name=name,
            sport_type=sport,
            session_order=1,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session


def _create_text(athlete_id: int | None = None, athlete_name: str | None = None) -> str:
    week_lines = ""
    if athlete_id is not None:
        week_lines = f"WEEK\nATHLETE_ID: {athlete_id}\n"
        if athlete_name is not None:
            week_lines += f"ATHLETE_NAME: {athlete_name}\n"
        week_lines += "\n"
    return f"""{week_lines}SESSION
ACTION: create
DATE: 2026-05-26
SPORT: running
NAME: Rodaje suave

BLOCK
VALUE: 30
UNIT: min

END
"""
