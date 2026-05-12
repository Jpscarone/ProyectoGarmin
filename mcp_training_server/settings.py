from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SupportedTransport = Literal["stdio", "http", "sse"]


@dataclass(frozen=True, slots=True)
class Settings:
    training_api_url: str
    training_api_token: str | None
    training_api_athlete_id: int | None
    mcp_transport: SupportedTransport
    mcp_host: str
    mcp_port: int
    mcp_http_path: str
    mcp_sse_path: str
    mcp_message_path: str


def _normalize_transport(raw_value: str | None) -> SupportedTransport:
    normalized = (raw_value or "stdio").strip().lower()
    if normalized in {"stdio"}:
        return "stdio"
    if normalized in {"http", "streamable-http", "streamable_http"}:
        return "http"
    if normalized in {"sse"}:
        return "sse"
    raise ValueError("MCP_TRANSPORT invalido. Usa stdio, http o sse.")


def _normalize_path(raw_value: str, *, default: str, trailing_slash: bool = False) -> str:
    normalized = (raw_value or default).strip() or default
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if trailing_slash and not normalized.endswith("/"):
        normalized += "/"
    if not trailing_slash and len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized


@lru_cache
def get_settings() -> Settings:
    raw_url = os.getenv("TRAINING_API_URL", "http://localhost:8000").strip()
    raw_athlete_id = (os.getenv("TRAINING_API_ATHLETE_ID") or "").strip()
    athlete_id: int | None = None
    if raw_athlete_id:
        athlete_id = int(raw_athlete_id)

    return Settings(
        training_api_url=raw_url.rstrip("/"),
        training_api_token=(os.getenv("TRAINING_API_TOKEN") or "").strip() or None,
        training_api_athlete_id=athlete_id,
        mcp_transport=_normalize_transport(os.getenv("MCP_TRANSPORT")),
        mcp_host=(os.getenv("MCP_HOST") or "127.0.0.1").strip() or "127.0.0.1",
        mcp_port=int((os.getenv("MCP_PORT") or "9000").strip() or "9000"),
        mcp_http_path=_normalize_path(os.getenv("MCP_HTTP_PATH", "/mcp"), default="/mcp"),
        mcp_sse_path=_normalize_path(os.getenv("MCP_SSE_PATH", "/sse"), default="/sse"),
        mcp_message_path=_normalize_path(
            os.getenv("MCP_MESSAGE_PATH", "/messages/"),
            default="/messages/",
            trailing_slash=True,
        ),
    )
