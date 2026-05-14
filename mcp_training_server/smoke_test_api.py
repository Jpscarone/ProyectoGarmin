from __future__ import annotations

import sys
from typing import Any

import httpx

try:
    from .settings import get_settings
except ImportError:
    from settings import get_settings


def _build_headers(token: str | None) -> dict[str, str]:
    if not token:
        raise RuntimeError("TRAINING_APP_MCP_TOKEN no esta configurado.")
    return {"Authorization": f"Bearer {token}"}


def _request(client: httpx.Client, path: str, headers: dict[str, str]) -> dict[str, Any] | list[dict[str, Any]]:
    response = client.get(path, headers=headers)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:200]}

    if response.status_code != 200:
        raise RuntimeError(f"{path} -> HTTP {response.status_code}: {payload}")
    if not isinstance(payload, (dict, list)):
        raise RuntimeError(f"{path} -> payload inesperado: {type(payload).__name__}")
    return payload


def main() -> int:
    settings = get_settings()
    headers = _build_headers(settings.training_app_mcp_token)

    targets = [
        "/api/mcp/ping",
        "/api/mcp/athletes",
        "/api/mcp/activities/recent?athlete_id=1&limit=5",
        "/api/mcp/compare/planned-vs-done?athlete_id=1",
        "/api/mcp/training/next-session-recommendation?athlete_id=1",
        "/api/mcp/health/summary?athlete_id=1",
        "/api/mcp/weekly/latest?athlete_id=1",
        "/api/mcp/training/status?athlete_id=1",
    ]

    with httpx.Client(base_url=settings.training_app_base_url, timeout=20.0) as client:
        for path in targets:
            payload = _request(client, path, headers)
            shape = type(payload).__name__
            print(f"OK {path} -> {shape}")

    print("Smoke test API MCP completado correctamente.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
