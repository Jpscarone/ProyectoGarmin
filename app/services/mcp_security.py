from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import get_settings


def verify_mcp_bearer_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected_tokens = [token for token in (settings.mcp_api_token, settings.mcp_write_api_token) if token]
    if not expected_tokens:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP_API_TOKEN no esta configurado.",
        )

    if authorization not in {f"Bearer {token}" for token in expected_tokens}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


def verify_mcp_write_bearer_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected_token = settings.mcp_write_api_token
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP_WRITE_API_TOKEN no esta configurado.",
        )

    if authorization != f"Bearer {expected_token}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
