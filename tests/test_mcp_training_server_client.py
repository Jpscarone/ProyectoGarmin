from __future__ import annotations

import importlib.util
import unittest

import httpx

MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None

if MCP_AVAILABLE:
    from mcp.server.fastmcp.exceptions import ToolError
    from mcp_training_server.client import TrainingAppApiClient
    from mcp_training_server.settings import Settings


@unittest.skipUnless(MCP_AVAILABLE, "mcp SDK no instalado en este entorno de tests")
class TrainingAppApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_athletes_returns_json_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/athletes")
            self.assertEqual(request.headers.get("Authorization"), "Bearer token-123")
            return httpx.Response(200, json=[{"id": 1, "name": "Pablo", "status": "active"}])

        client = _build_client(handler)
        payload = await client.get_athletes()

        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["name"], "Pablo")

    async def test_get_training_status_maps_401_to_clear_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "Unauthorized"})

        client = _build_client(handler)
        with self.assertRaises(ToolError) as ctx:
            await client.get_training_status(athlete_id=1)

        self.assertIn("TRAINING_APP_MCP_TOKEN", str(ctx.exception))

    async def test_compare_planned_vs_done_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/compare/planned-vs-done")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("date"), "2026-05-13")
            self.assertEqual(request.url.params.get("activity_id"), "22")
            self.assertEqual(request.url.params.get("planned_session_id"), "33")
            return httpx.Response(200, json={"date": "2026-05-13", "match": {"source": "none"}})

        client = _build_client(handler)
        payload = await client.compare_planned_vs_done(
            athlete_id=1,
            date="2026-05-13",
            activity_id=22,
            planned_session_id=33,
        )

        self.assertEqual(payload["date"], "2026-05-13")

    async def test_get_next_session_recommendation_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/next-session-recommendation")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("reference_date"), "2026-05-13")
            self.assertEqual(request.url.params.get("planned_session_id"), "44")
            return httpx.Response(200, json={"reference_date": "2026-05-13", "recommendation": {"decision": "keep"}})

        client = _build_client(handler)
        payload = await client.get_next_session_recommendation(
            athlete_id=1,
            reference_date="2026-05-13",
            planned_session_id=44,
        )

        self.assertEqual(payload["recommendation"]["decision"], "keep")

    async def test_get_week_load_summary_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/training/week-load-summary")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("week_start_date"), "2026-05-11")
            self.assertEqual(request.url.params.get("compare_previous"), "false")
            return httpx.Response(200, json={"week": {"start_date": "2026-05-11"}, "recommendation": {"status": "balanced"}})

        client = _build_client(handler)
        payload = await client.get_week_load_summary(
            athlete_id=1,
            week_start_date="2026-05-11",
            compare_previous=False,
        )

        self.assertEqual(payload["recommendation"]["status"], "balanced")

    async def test_get_session_analysis_payload_passes_optional_query_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mcp/analysis/session-payload")
            self.assertEqual(request.url.params.get("athlete_id"), "1")
            self.assertEqual(request.url.params.get("planned_session_id"), "12")
            self.assertEqual(request.url.params.get("activity_id"), "34")
            self.assertEqual(request.url.params.get("date"), "2026-05-13")
            return httpx.Response(200, json={"resolved_by": "planned_session_id", "data_quality": {"has_metrics_json": False}})

        client = _build_client(handler)
        payload = await client.get_session_analysis_payload(
            athlete_id=1,
            planned_session_id=12,
            activity_id=34,
            date="2026-05-13",
        )

        self.assertEqual(payload["resolved_by"], "planned_session_id")


def _build_client(handler) -> TrainingAppApiClient:
    settings = Settings(
        training_app_base_url="http://testserver",
        training_app_mcp_token="token-123",
        mcp_transport="http",
        mcp_host="127.0.0.1",
        mcp_port=9000,
        mcp_http_path="/mcp",
        mcp_sse_path="/sse",
        mcp_message_path="/messages/",
    )

    class TestAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    return TrainingAppApiClient(settings, async_client_factory=TestAsyncClient)
