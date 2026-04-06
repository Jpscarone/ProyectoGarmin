from __future__ import annotations

from app.config import Settings
from app.services.openai_client import (
    OpenAIIntegrationError,
    build_openai_client,
    get_openai_max_output_tokens,
    get_openai_model,
    get_openai_timeout_sec,
)

__all__ = [
    "OpenAIIntegrationError",
    "build_openai_client",
    "get_openai_model",
    "get_openai_timeout_sec",
    "get_openai_max_output_tokens",
]


def get_openai_client(settings: Settings | None = None):
    try:
        return build_openai_client(settings)
    except OpenAIIntegrationError:
        return None
