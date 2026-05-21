from __future__ import annotations

import json
import hashlib
from datetime import date
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db.models.athlete import Athlete
from app.db.models.health_ai_analysis import HealthAiAnalysis
from app.schemas.daily_health_metric import HealthAIAnalysisResult
from app.services.health_readiness_service import (
    build_health_llm_json,
    build_health_readiness_summary,
    build_health_training_context,
    evaluate_health_readiness,
)
from app.services.openai_client import (
    OpenAIIntegrationError,
    build_openai_client,
    get_openai_max_output_tokens,
    get_openai_model,
)


HEALTH_AI_SYSTEM_PROMPT = """
Sos un analista de salud y readiness para entrenamiento.
Tu trabajo es interpretar un JSON resumido de readiness y devolver una lectura breve, prudente y util.

Reglas obligatorias:
- No diagnostiques enfermedades.
- No reemplaces consejo medico.
- No recomiendes medicacion ni estudios clinicos.
- Enfocate solo en entrenamiento, carga y recuperacion.
- Si faltan datos, decilo con claridad.
- Respetá la evaluacion local de readiness, aunque podés matizarla con prudencia.
- No uses markdown.
- Devolve siempre JSON estricto compatible con el schema pedido.

Objetivo:
- resumir el estado actual para entrenar
- traducir el readiness en una recomendacion practica
- marcar los factores principales
- indicar que conviene vigilar sin sonar alarmista
""".strip()


def create_health_ai_analysis(
    db: Session,
    *,
    athlete_id: int,
    reference_date: date,
    llm_json: dict[str, Any],
    ai_response_json: dict[str, Any],
    summary: str | None,
    training_recommendation: str | None,
    risk_level: str | None,
    model_name: str | None,
    llm_json_hash: str | None = None,
    source: str = "manual",
    force: bool = False,
) -> HealthAiAnalysis:
    analysis = get_latest_health_ai_analysis_for_date(db, athlete_id, reference_date)
    if analysis is None:
        analysis = HealthAiAnalysis(
            athlete_id=athlete_id,
            reference_date=reference_date,
        )
    elif not force:
        return analysis

    analysis.llm_json = jsonable_encoder(llm_json)
    analysis.llm_json_hash = llm_json_hash or build_health_llm_json_hash(llm_json)
    analysis.ai_response_json = jsonable_encoder(ai_response_json)
    analysis.summary = summary
    analysis.training_recommendation = training_recommendation
    analysis.risk_level = risk_level
    analysis.model_name = model_name
    analysis.source = source
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def build_health_llm_json_hash(llm_json: dict[str, Any]) -> str:
    serialized = json.dumps(jsonable_encoder(llm_json), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def should_auto_run_health_ai_analysis(
    latest_analysis: HealthAiAnalysis | None,
    current_llm_json_hash: str,
) -> bool:
    if latest_analysis is None:
        return True
    if not latest_analysis.llm_json_hash:
        return True
    return latest_analysis.llm_json_hash != current_llm_json_hash


def get_latest_health_ai_analysis_for_date(
    db: Session,
    athlete_id: int,
    reference_date: date,
) -> HealthAiAnalysis | None:
    statement = (
        select(HealthAiAnalysis)
        .where(
            HealthAiAnalysis.athlete_id == athlete_id,
            HealthAiAnalysis.reference_date == reference_date,
        )
        .options(selectinload(HealthAiAnalysis.athlete))
        .order_by(HealthAiAnalysis.updated_at.desc(), HealthAiAnalysis.created_at.desc(), HealthAiAnalysis.id.desc())
    )
    return db.scalar(statement)


def list_health_ai_analyses_for_athlete(
    db: Session,
    athlete_id: int,
    limit: int | None = None,
) -> list[HealthAiAnalysis]:
    statement = (
        select(HealthAiAnalysis)
        .where(HealthAiAnalysis.athlete_id == athlete_id)
        .options(selectinload(HealthAiAnalysis.athlete))
        .order_by(
            HealthAiAnalysis.reference_date.desc(),
            HealthAiAnalysis.updated_at.desc(),
            HealthAiAnalysis.created_at.desc(),
            HealthAiAnalysis.id.desc(),
        )
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list(db.scalars(statement).all())


def get_or_create_health_ai_analysis(
    db: Session,
    *,
    athlete_id: int,
    reference_date: date,
    force: bool = False,
    source: str = "manual",
) -> tuple[HealthAiAnalysis | None, str]:
    athlete = db.get(Athlete, athlete_id)
    if athlete is None:
        raise ValueError(f"No se encontro Athlete #{athlete_id}.")

    existing = get_latest_health_ai_analysis_for_date(db, athlete_id, reference_date)
    if existing is not None and not force:
        return existing, "existing"

    summary = build_health_readiness_summary(db, athlete_id, reference_date)
    evaluation = evaluate_health_readiness(summary)
    if evaluation.readiness_score is None:
        return existing, "insufficient_data"

    training_context = build_health_training_context(db, athlete_id, reference_date)
    llm_json = build_health_llm_json(
        athlete,
        summary,
        evaluation,
        reference_date,
        training_context=training_context,
    )
    analysis_payload = analyze_health_readiness_with_ai(llm_json)
    analysis = create_health_ai_analysis(
        db,
        athlete_id=athlete_id,
        reference_date=reference_date,
        llm_json=llm_json,
        llm_json_hash=build_health_llm_json_hash(llm_json),
        ai_response_json=analysis_payload,
        summary=analysis_payload.get("summary"),
        training_recommendation=analysis_payload.get("training_recommendation"),
        risk_level=analysis_payload.get("risk_level"),
        model_name=_safe_model_name(),
        source=source,
        force=force or existing is None,
    )
    return analysis, ("updated" if existing is not None else "created")


def analyze_health_readiness_with_ai(llm_json: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise OpenAIIntegrationError("OPENAI_API_KEY no configurada.")

    model = get_openai_model(settings)
    client = build_openai_client(settings)
    payload_json = json.dumps(jsonable_encoder(llm_json), ensure_ascii=False)

    try:
        response = client.responses.parse(
            model=model,
            instructions=HEALTH_AI_SYSTEM_PROMPT,
            input=payload_json,
            text_format=HealthAIAnalysisResult,
            temperature=0.2,
            max_output_tokens=min(get_openai_max_output_tokens("session", settings), 700),
            timeout=settings.openai_timeout_sec,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise OpenAIIntegrationError("OpenAI no devolvio una salida utilizable para salud.")
        result = parsed if isinstance(parsed, HealthAIAnalysisResult) else HealthAIAnalysisResult.model_validate(parsed)
        return result.model_dump()
    except APITimeoutError as exc:
        raise OpenAIIntegrationError(
            f"OpenAI no respondio a tiempo ({settings.openai_timeout_sec}s)."
        ) from exc
    except APIConnectionError as exc:
        raise OpenAIIntegrationError("No se pudo conectar con OpenAI.") from exc
    except RateLimitError as exc:
        raise OpenAIIntegrationError("OpenAI rechazo temporalmente la solicitud por limite de uso.") from exc
    except APIError as exc:
        raise OpenAIIntegrationError(f"OpenAI devolvio un error: {exc}") from exc
    except ValidationError as exc:
        raise OpenAIIntegrationError(f"OpenAI devolvio un JSON invalido para salud: {exc}") from exc
    except Exception as exc:
        raise OpenAIIntegrationError(f"Error inesperado al analizar readiness con OpenAI: {exc}") from exc


def _safe_model_name() -> str | None:
    try:
        return get_openai_model(get_settings())
    except Exception:
        return None
