from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db.models import athlete  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.db.models.athlete import Athlete


class ApiMcpSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_token = os.environ.get("MCP_API_TOKEN")
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(Athlete(name="Atleta MCP"))
        self.db.commit()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self.previous_token is None:
            os.environ.pop("MCP_API_TOKEN", None)
        else:
            os.environ["MCP_API_TOKEN"] = self.previous_token
        get_settings.cache_clear()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_missing_authorization_returns_401(self) -> None:
        os.environ["MCP_API_TOKEN"] = "secret-token"
        get_settings.cache_clear()

        response = self.client.get("/api/mcp/week-context")

        self.assertEqual(response.status_code, 401)

    def test_wrong_token_returns_401(self) -> None:
        os.environ["MCP_API_TOKEN"] = "secret-token"
        get_settings.cache_clear()

        response = self.client.get(
            "/api/mcp/week-context",
            headers={"Authorization": "Bearer wrong-token"},
        )

        self.assertEqual(response.status_code, 401)

    def test_correct_token_returns_200(self) -> None:
        os.environ["MCP_API_TOKEN"] = "secret-token"
        get_settings.cache_clear()

        response = self.client.get(
            "/api/mcp/week-context",
            headers={"Authorization": "Bearer secret-token"},
        )

        self.assertEqual(response.status_code, 200)

    def test_missing_env_token_returns_500(self) -> None:
        os.environ.pop("MCP_API_TOKEN", None)
        get_settings.cache_clear()

        response = self.client.get(
            "/api/mcp/week-context",
            headers={"Authorization": "Bearer anything"},
        )

        self.assertEqual(response.status_code, 500)
