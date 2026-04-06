from __future__ import annotations

from functools import lru_cache
from typing import Literal

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

from app.config import Settings, get_settings


AnalysisType = Literal["session", "week"]


class OpenAIIntegrationError(RuntimeError):
    """Error controlado para la capa de integración con OpenAI."""


@lru_cache
def _cached_client(api_key: str, timeout_sec: float) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        timeout=timeout_sec,
        max_retries=0,
    )


def build_openai_client(settings: Settings | None = None) -> OpenAI:
    current_settings = settings or get_settings()
    if not current_settings.openai_api_key:
        raise OpenAIIntegrationError("OPENAI_API_KEY no configurada.")
    return _cached_client(
        current_settings.openai_api_key,
        current_settings.openai_timeout_sec,
    )


def get_openai_model(settings: Settings | None = None) -> str:
    current_settings = settings or get_settings()
    return current_settings.openai_model


def get_openai_timeout_sec(settings: Settings | None = None) -> float:
    current_settings = settings or get_settings()
    return current_settings.openai_timeout_sec


def get_openai_max_output_tokens(
    analysis_type: AnalysisType = "session",
    settings: Settings | None = None,
) -> int:
    current_settings = settings or get_settings()
    if analysis_type == "week":
        return current_settings.openai_max_output_tokens_week
    return current_settings.openai_max_output_tokens_session


def generate_text_analysis(
    prompt: str,
    analysis_type: AnalysisType = "session",
    settings: Settings | None = None,
) -> str:
    current_settings = settings or get_settings()
    client = build_openai_client(current_settings)
    model = get_openai_model(current_settings)
    max_output_tokens = get_openai_max_output_tokens(analysis_type, current_settings)

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=max_output_tokens,
        )
    except APITimeoutError as exc:
        raise OpenAIIntegrationError(
            f"OpenAI no respondio a tiempo ({current_settings.openai_timeout_sec}s)."
        ) from exc
    except APIConnectionError as exc:
        raise OpenAIIntegrationError("No se pudo conectar con OpenAI.") from exc
    except RateLimitError as exc:
        raise OpenAIIntegrationError("OpenAI rechazo temporalmente la solicitud por limite de uso.") from exc
    except APIError as exc:
        raise OpenAIIntegrationError(f"OpenAI devolvio un error: {exc}") from exc
    except Exception as exc:
        raise OpenAIIntegrationError(f"Error inesperado al generar analisis con OpenAI: {exc}") from exc

    output_text = getattr(response, "output_text", None)
    if not output_text:
        raise OpenAIIntegrationError("OpenAI no devolvio texto utilizable.")
    return output_text.strip()
