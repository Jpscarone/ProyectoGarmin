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
