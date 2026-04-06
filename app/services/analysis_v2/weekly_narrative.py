from __future__ import annotations

import json
import logging
from statistics import mean
from typing import Any, Mapping

from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError
from pydantic import ValidationError

from app.config import get_settings
from app.services.openai_client import (
    OpenAIIntegrationError,
    build_openai_client,
    get_openai_max_output_tokens,
    get_openai_model,
)
from app.services.analysis_v2.weekly_schemas import (
    WeeklyNarrativeLLMOutput,
    WeeklyNarrativeResult,
)


logger = logging.getLogger(__name__)

WEEKLY_SYSTEM_PROMPT = """
Sos un analista de entrenamiento de endurance enfocado en lectura semanal.
Tu tarea es interpretar la semana completa de un atleta y ayudar a decidir que hacer la semana siguiente.

Reglas obligatorias:
- Prioriza tendencias y decision practica sobre repetir numeros.
- No inventes datos ni uses precision falsa.
- Reconoce incertidumbre si faltan datos.
- No hagas diagnosticos medicos.
- No uses markdown dentro de los campos.
- Devuelve siempre JSON estricto compatible con el schema.

Objetivos:
- identificar que tipo de semana fue realmente
- interpretar carga, consistencia, balance y fatiga
- detectar si la semana quedo ordenada o caotica
- dejar una recomendacion concreta para la proxima semana
""".strip()


def build_weekly_llm_payload(context: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "athlete": {
            "name": context.athlete.name,
            "primary_sport": context.athlete.primary_sport,
            "max_hr": context.athlete.max_hr,
            "vo2max": context.athlete.vo2max,
        },
        "week": {
            "week_start_date": _iso(context.week_start_date),
            "week_end_date": _iso(context.week_end_date),
            "activities": [
                {
                    "date": _iso(item.activity_date),
                    "title": item.title,
                    "sport_type": item.sport_type,
                    "duration_sec": item.duration_sec,
                    "distance_m": item.distance_m,
                    "elevation_gain_m": item.elevation_gain_m,
                    "avg_hr": item.avg_hr,
                    "avg_pace_sec_km": item.avg_pace_sec_km,
                    "session_analysis_summary": item.session_analysis_summary,
                }
                for item in context.activities
            ],
            "planned_sessions": [
                {
                    "date": _iso(item.session_date),
                    "title": item.title,
                    "sport_type": item.sport_type,
                    "session_type": item.session_type,
                    "expected_duration_min": item.expected_duration_min,
                    "expected_distance_km": item.expected_distance_km,
                    "matched": item.matched,
                }
                for item in context.planned_sessions
            ],
        },
        "metrics": metrics,
        "previous_weeks": [
            {
                "week_start_date": _iso(item.week_start_date),
                "week_end_date": _iso(item.week_end_date),
                "activity_count": item.activity_count,
                "total_duration_sec": item.total_duration_sec,
                "total_distance_m": item.total_distance_m,
                "total_elevation_gain_m": item.total_elevation_gain_m,
                "planned_sessions": item.planned_sessions,
                "completed_sessions": item.completed_sessions,
            }
            for item in context.previous_weeks
        ],
        "missing_data": _collect_missing_data(context, metrics),
    }


def generate_weekly_narrative(context: Any, metrics: Mapping[str, Any]) -> WeeklyNarrativeResult:
    settings = get_settings()
    payload = build_weekly_llm_payload(context, metrics)
    fallback = _build_weekly_fallback_output(context, metrics)

    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY no configurada. Se usa narrativa fallback para WeeklyAnalysis V2.")
        return WeeklyNarrativeResult.from_llm_output(
            fallback,
            narrative_status="skipped_no_api_key",
            provider=None,
            model=None,
            llm_json={
                "provider": None,
                "model": None,
                "status": "skipped_no_api_key",
                "payload": payload,
                "structured_output": fallback.to_structured_output().model_dump(),
            },
            error_message="OPENAI_API_KEY no configurada.",
        )

    model = get_openai_model(settings)
    try:
        client = build_openai_client(settings)
    except OpenAIIntegrationError:
        return WeeklyNarrativeResult.from_llm_output(
            fallback,
            narrative_status="error",
            provider="openai",
            model=model,
            llm_json={
                "provider": "openai",
                "model": model,
                "status": "client_unavailable",
                "payload": payload,
                "structured_output": fallback.to_structured_output().model_dump(),
            },
            error_message="No se pudo inicializar el cliente OpenAI.",
        )

    try:
        response = client.responses.parse(
            model=model,
            instructions=WEEKLY_SYSTEM_PROMPT,
            input=json.dumps(payload, ensure_ascii=False),
            text_format=WeeklyNarrativeLLMOutput,
            temperature=0.3,
            max_output_tokens=get_openai_max_output_tokens("week", settings),
            timeout=settings.openai_timeout_sec,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("OpenAI no devolvio salida parseada.")
        llm_output = parsed if isinstance(parsed, WeeklyNarrativeLLMOutput) else WeeklyNarrativeLLMOutput.model_validate(parsed)
        llm_output = _merge_weekly_output_with_fallback(llm_output, fallback)
        return WeeklyNarrativeResult.from_llm_output(
            llm_output,
            narrative_status="completed",
            provider="openai",
            model=model,
            llm_json={
                "provider": "openai",
                "model": model,
                "status": "completed",
                "response_id": getattr(response, "id", None),
                "usage": _response_usage_to_dict(getattr(response, "usage", None)),
                "payload": payload,
                "structured_output": llm_output.to_structured_output().model_dump(),
            },
        )
    except (RateLimitError, APITimeoutError, APIConnectionError, APIError, ValidationError, ValueError) as exc:
        logger.exception("Fallo generate_weekly_narrative con OpenAI; se usa fallback.")
        status = "error"
        if isinstance(exc, RateLimitError):
            status = "rate_limited"
        elif isinstance(exc, APITimeoutError):
            status = "timeout"
        return WeeklyNarrativeResult.from_llm_output(
            fallback,
            narrative_status=status,
            provider="openai",
            model=model,
            llm_json={
                "provider": "openai",
                "model": model,
                "status": status,
                "payload": payload,
                "structured_output": fallback.to_structured_output().model_dump(),
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
            error_message=str(exc),
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Error inesperado en generate_weekly_narrative; se usa fallback.")
        return WeeklyNarrativeResult.from_llm_output(
            fallback,
            narrative_status="error",
            provider="openai",
            model=model,
            llm_json={
                "provider": "openai",
                "model": model,
                "status": "error",
                "payload": payload,
                "structured_output": fallback.to_structured_output().model_dump(),
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
            error_message=str(exc),
        )


def _build_weekly_fallback_output(context: Any, metrics: Mapping[str, Any]) -> WeeklyNarrativeLLMOutput:
    scores = metrics.get("scores", {})
    flags = metrics.get("derived_flags", {})
    totals = metrics.get("totals", {})
    compliance = metrics.get("compliance", {})
    trends = metrics.get("trends", {})
    distribution = metrics.get("distribution", {})

    load_score = scores.get("load_score")
    consistency_score = scores.get("consistency_score")
    fatigue_score = scores.get("fatigue_score")
    balance_score = scores.get("balance_score")

    week_type = _detect_week_type(metrics)
    positives: list[str] = []
    risks: list[str] = []
    recommendations: list[str] = []
    findings: list[str] = []

    if compliance.get("compliance_ratio_pct") is not None:
        findings.append(f"El cumplimiento semanal quedo en {round(compliance['compliance_ratio_pct'])}%.")
    if totals.get("activity_count"):
        findings.append(f"Se registraron {totals['activity_count']} actividades en la semana.")

    if not flags.get("undertraining_flag") and not flags.get("overload_flag"):
        positives.append("La carga semanal no muestra un desvio extremo respecto del contexto reciente.")
    if consistency_score is not None and consistency_score >= 70:
        positives.append("La distribucion de la semana fue razonablemente consistente.")
    if balance_score is not None and balance_score >= 70:
        positives.append("La mezcla de deportes y tipos de carga se ve aceptable para esta fase.")

    if flags.get("overload_flag"):
        risks.append("La carga semanal parece alta en comparacion con las semanas previas.")
        recommendations.append("Bajar ligeramente el volumen o proteger mejor los dias suaves en la proxima semana.")
    if flags.get("undertraining_flag"):
        risks.append("La semana quedo por debajo de la carga reciente o de lo planificado.")
        recommendations.append("Recuperar continuidad sin compensar de golpe con una semana excesiva.")
    if flags.get("poor_distribution_flag"):
        risks.append("La carga quedo demasiado concentrada en pocos dias.")
        recommendations.append("Distribuir mejor la carga para evitar acumulacion innecesaria.")
    if flags.get("high_fatigue_risk_flag"):
        risks.append("La combinacion de carga y fatiga sugiere vigilar la recuperacion.")
        recommendations.append("Priorizar descanso, sueño y control de intensidad al inicio de la proxima semana.")
    if flags.get("low_consistency_flag"):
        risks.append("La consistencia semanal fue baja.")
        recommendations.append("Buscar mas regularidad entre dias entrenados y dias vacios.")

    duration_delta = trends.get("duration_vs_prev_avg_pct")
    if duration_delta is not None:
        findings.append(f"La duracion semanal quedo {duration_delta:+.1f}% vs el promedio reciente.")

    if not positives:
        positives.append("La semana deja una base util, aunque con informacion parcial en algunos frentes.")
    if not risks:
        risks.append("No aparecen alertas mayores, pero conviene confirmar la tendencia con otra semana similar.")
    if not recommendations:
        recommendations.append("Mantener la progresion y revisar si el objetivo principal de la semana siguiente pide ajustar volumen o intensidad.")

    summary_short = _weekly_summary_short(context, metrics, week_type)
    analysis_natural = _weekly_analysis_natural(context, metrics)
    coach_conclusion = _weekly_coach_conclusion(load_score, consistency_score, fatigue_score, week_type)
    next_week_recommendation = recommendations[0]

    tags = _unique_items(
        [
            context.athlete.primary_sport or "sin_deporte",
            week_type,
            "overload" if flags.get("overload_flag") else "",
            "undertraining" if flags.get("undertraining_flag") else "",
            "fatigue_risk" if flags.get("high_fatigue_risk_flag") else "",
        ]
    )

    return WeeklyNarrativeLLMOutput(
        summary_short=summary_short,
        analysis_natural=analysis_natural,
        coach_conclusion=coach_conclusion,
        next_week_recommendation=next_week_recommendation,
        week_type_detected=week_type,
        main_findings=findings[:4],
        risks=risks[:4],
        positives=positives[:4],
        recommendations=recommendations[:4],
        tags=tags[:6],
    )


def _merge_weekly_output_with_fallback(
    llm_output: WeeklyNarrativeLLMOutput,
    fallback_output: WeeklyNarrativeLLMOutput,
) -> WeeklyNarrativeLLMOutput:
    merged = llm_output.model_copy(deep=True)
    for field_name in ("summary_short", "analysis_natural", "coach_conclusion", "next_week_recommendation", "week_type_detected"):
        if not getattr(merged, field_name, "").strip():
            setattr(merged, field_name, getattr(fallback_output, field_name))
    for field_name in ("main_findings", "risks", "positives", "recommendations", "tags"):
        if not getattr(merged, field_name):
            setattr(merged, field_name, list(getattr(fallback_output, field_name)))
    return merged


def _weekly_summary_short(context: Any, metrics: Mapping[str, Any], week_type: str) -> str:
    totals = metrics.get("totals", {})
    compliance = metrics.get("compliance", {})
    return (
        f"Semana {week_type}: {totals.get('activity_count', 0)} actividades, "
        f"{round((totals.get('total_duration_sec') or 0) / 3600.0, 1)} h, "
        f"cumplimiento {round(compliance.get('compliance_ratio_pct') or 0)}%."
    )


def _weekly_analysis_natural(context: Any, metrics: Mapping[str, Any]) -> str:
    totals = metrics.get("totals", {})
    scores = metrics.get("scores", {})
    trends = metrics.get("trends", {})
    fragments = [
        f"La semana tuvo {totals.get('activity_count', 0)} actividades y "
        f"{round((totals.get('total_duration_sec') or 0) / 3600.0, 1)} horas totales.",
        f"Los scores sugieren carga {round(scores.get('load_score') or 0)}, "
        f"consistencia {round(scores.get('consistency_score') or 0)}, "
        f"fatiga {round(scores.get('fatigue_score') or 0)} y balance {round(scores.get('balance_score') or 0)}.",
    ]
    if trends.get("duration_vs_prev_avg_pct") is not None:
        fragments.append(
            f"Contra el promedio reciente, la duracion cambio {trends['duration_vs_prev_avg_pct']:+.1f}% "
            f"y la distancia {trends.get('distance_vs_prev_avg_pct', 0):+.1f}%."
        )
    return " ".join(fragments)


def _weekly_coach_conclusion(
    load_score: float | None,
    consistency_score: float | None,
    fatigue_score: float | None,
    week_type: str,
) -> str:
    if week_type == "carga_excesiva":
        return "La semana fue exigente y conviene leerla como una semana de carga alta con riesgo de acumular fatiga."
    if week_type == "carga_baja":
        return "La semana quedo liviana y puede servir como descarga o como señal de falta de continuidad."
    if week_type == "consistente":
        return "La semana se ve ordenada, con una carga razonable y una distribucion util para seguir progresando."
    if (load_score or 0) >= 75 and (consistency_score or 0) >= 70 and (fatigue_score or 0) < 75:
        return "La semana deja una base positiva y relativamente controlada para construir la siguiente."
    return "La semana necesita una lectura prudente porque mezcla senales utiles con algunos desequilibrios."


def _detect_week_type(metrics: Mapping[str, Any]) -> str:
    flags = metrics.get("derived_flags", {})
    scores = metrics.get("scores", {})
    if flags.get("overload_flag"):
        return "carga_excesiva"
    if flags.get("undertraining_flag"):
        return "carga_baja"
    if (scores.get("consistency_score") or 0) >= 70 and not flags.get("poor_distribution_flag"):
        return "consistente"
    return "mixta"


def _collect_missing_data(context: Any, metrics: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    if not context.activities:
        missing.append("Sin actividades registradas en la semana.")
    if not context.planned_sessions:
        missing.append("Sin sesiones planificadas en la semana.")
    if not context.session_analyses:
        missing.append("Sin analisis V2 de sesiones para enriquecer la lectura.")
    if not context.health_days:
        missing.append("Sin metricas de salud semanales.")
    if not (metrics.get("distribution") or {}).get("time_in_zones_sec"):
        missing.append("Sin distribucion de zonas agregada.")
    return missing


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _response_usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {"value": str(usage)}


def _unique_items(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result
