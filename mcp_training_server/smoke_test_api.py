from __future__ import annotations

import sys
from typing import Any

import httpx

from settings import get_settings


def _build_headers(token: str | None) -> dict[str, str]:
    if not token:
        raise RuntimeError("TRAINING_API_TOKEN no esta configurado.")
    return {"Authorization": f"Bearer {token}"}


def _request(client: httpx.Client, path: str, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get(path, headers=headers)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:200]}

    if response.status_code != 200:
        raise RuntimeError(f"{path} -> HTTP {response.status_code}: {payload}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} -> payload inesperado: {type(payload).__name__}")
    return payload


def main() -> int:
    settings = get_settings()
    headers = _build_headers(settings.training_api_token)
    athlete_query = (
        f"athlete_id={settings.training_api_athlete_id}"
        if settings.training_api_athlete_id is not None
        else "athlete_id=1"
    )

    targets = [
        (f"/api/mcp/week-context?{athlete_query}", "mcp_week_context_v1"),
        (f"/api/mcp/last-activity-feedback?{athlete_query}", "mcp_last_activity_feedback_v1"),
        (f"/api/mcp/next-session-context?{athlete_query}", "mcp_next_session_context_v1"),
        (f"/api/mcp/session-feedback?{athlete_query}&date=2026-05-02", "mcp_session_feedback_v1"),
    ]

    with httpx.Client(base_url=settings.training_api_url, timeout=20.0) as client:
        for path, expected_schema in targets:
            payload = _request(client, path, headers)
            actual_schema = payload.get("schema_version")
            if actual_schema != expected_schema:
                raise RuntimeError(
                    f"{path} -> schema_version inesperado: {actual_schema!r} (esperado {expected_schema!r})"
                )
            print(f"OK {path} -> {actual_schema}")

    print("Smoke test API MCP completado correctamente.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
