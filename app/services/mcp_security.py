from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import get_settings


def verify_mcp_bearer_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected_token = settings.mcp_api_token
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP_API_TOKEN no esta configurado.",
        )

    expected_header = f"Bearer {expected_token}"
    if authorization != expected_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
