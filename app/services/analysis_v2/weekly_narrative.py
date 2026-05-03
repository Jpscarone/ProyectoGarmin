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

WEEKLY_HEALTH_SLEEP_HOURS_LOW = 6.5
WEEKLY_HEALTH_SLEEP_HOURS_MODERATE = 7.0
WEEKLY_HEALTH_SLEEP_SCORE_LOW = 65
WEEKLY_HEALTH_SLEEP_SCORE_MODERATE = 75
WEEKLY_HEALTH_STRESS_HIGH = 35
WEEKLY_HEALTH_STRESS_MODERATE = 28
WEEKLY_HEALTH_BODY_BATTERY_LOW = 35
WEEKLY_HEALTH_BODY_BATTERY_MODERATE = 50
WEEKLY_HEALTH_RECOVERY_HIGH = 24.0
WEEKLY_HEALTH_RECOVERY_MODERATE = 16.0

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

Uso del contexto:
- Si contextual_factors.has_relevant_context es false, no menciones salud o recuperacion como relleno.
- Si hay contexto relevante, usalo solo para matizar la lectura semanal.
- No conviertas la salud en explicacion unica de toda la semana.
- No hagas inferencias medicas ni subjetivas.
""".strip()


def build_weekly_llm_payload(context: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    contextual_factors = build_weekly_contextual_factors(context, metrics)
    filtered_metrics = {
        "totals": metrics.get("totals", {}),
        "distribution": metrics.get("distribution", {}),
        "compliance": metrics.get("compliance", {}),
        "trends": metrics.get("trends", {}),
        "consistency": metrics.get("consistency", {}),
        "session_analysis_aggregate": metrics.get("session_analysis_aggregate", {}),
        "derived_flags": metrics.get("derived_flags", {}),
        "scores": metrics.get("scores", {}),
        "rule_thresholds": metrics.get("rule_thresholds", {}),
    }
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
        "metrics": filtered_metrics,
        "contextual_factors": contextual_factors,
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


def build_weekly_health_context_summary(context: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    health_context = metrics.get("health_context", {}) if isinstance(metrics, Mapping) else {}
    if not health_context or not health_context.get("days_with_health"):
        return {"relevant": False, "summary": None, "signals": []}

    signals: list[str] = []
    critical = False
    moderate_signals = 0

    avg_sleep_hours = health_context.get("avg_sleep_hours")
    avg_sleep_score = health_context.get("avg_sleep_score")
    avg_stress = health_context.get("avg_stress")
    avg_body_battery_end = health_context.get("avg_body_battery_end")
    avg_recovery_time_hours = health_context.get("avg_recovery_time_hours")

    if avg_sleep_hours is not None:
        if avg_sleep_hours < WEEKLY_HEALTH_SLEEP_HOURS_LOW:
            signals.append(f"sueño medio bajo ({avg_sleep_hours:.1f} h)")
            critical = True
        elif avg_sleep_hours < WEEKLY_HEALTH_SLEEP_HOURS_MODERATE:
            signals.append(f"sueño medio algo corto ({avg_sleep_hours:.1f} h)")
            moderate_signals += 1

    if avg_sleep_score is not None:
        if avg_sleep_score < WEEKLY_HEALTH_SLEEP_SCORE_LOW:
            signals.append(f"sleep score medio bajo ({round(avg_sleep_score)})")
            critical = True
        elif avg_sleep_score < WEEKLY_HEALTH_SLEEP_SCORE_MODERATE:
            signals.append(f"sleep score medio moderado ({round(avg_sleep_score)})")
            moderate_signals += 1

    if avg_stress is not None:
        if avg_stress >= WEEKLY_HEALTH_STRESS_HIGH:
            signals.append(f"estres medio alto ({round(avg_stress)})")
            critical = True
        elif avg_stress >= WEEKLY_HEALTH_STRESS_MODERATE:
            signals.append(f"estres medio sostenido ({round(avg_stress)})")
            moderate_signals += 1

    if avg_body_battery_end is not None:
        if avg_body_battery_end < WEEKLY_HEALTH_BODY_BATTERY_LOW:
            signals.append(f"body battery final baja ({round(avg_body_battery_end)})")
            critical = True
        elif avg_body_battery_end < WEEKLY_HEALTH_BODY_BATTERY_MODERATE:
            signals.append(f"body battery final justa ({round(avg_body_battery_end)})")
            moderate_signals += 1

    if avg_recovery_time_hours is not None:
        if avg_recovery_time_hours >= WEEKLY_HEALTH_RECOVERY_HIGH:
            signals.append(f"recuperacion media pendiente alta ({round(avg_recovery_time_hours)} h)")
            critical = True
        elif avg_recovery_time_hours >= WEEKLY_HEALTH_RECOVERY_MODERATE:
            signals.append(f"recuperacion media exigente ({round(avg_recovery_time_hours)} h)")
            moderate_signals += 1

    relevant = critical or moderate_signals >= 2
    if not relevant:
        return {"relevant": False, "summary": None, "signals": []}

    scores = metrics.get("scores", {}) if isinstance(metrics, Mapping) else {}
    fatigue_score = scores.get("fatigue_score")
    consistency_score = scores.get("consistency_score")
    effects: list[str] = []
    if fatigue_score is not None and fatigue_score >= 65:
        effects.append("puede haber aumentado la fatiga acumulada")
    if consistency_score is not None and consistency_score < 70:
        effects.append("puede haber reducido la calidad de la semana")
    if not effects:
        effects.append("puede matizar la lectura de la carga semanal")

    summary = (
        f"La semana estuvo acompañada por señales de recuperacion mejorable ({', '.join(signals)}), "
        f"lo que {' y '.join(effects)}."
    )
    return {"relevant": True, "summary": summary, "signals": signals}


def build_weekly_contextual_factors(context: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    health_context = build_weekly_health_context_summary(context, metrics)
    return {
        "has_relevant_context": bool(health_context["relevant"]),
        "health_relevant": health_context["relevant"],
        "health_summary": health_context["summary"],
        "summary": health_context["summary"],
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

    if flags.get("intensity_distribution_imbalance_flag"):
        risks.insert(0, "La distribucion de intensidad quedo desequilibrada, con demasiada carga en zonas altas.")
    if not flags.get("undertraining_flag") and not flags.get("overload_flag"):
        positives.append("La carga semanal no muestra un desvio extremo respecto del contexto reciente.")
    if consistency_score is not None and consistency_score >= 70:
        positives.append("La distribucion de la semana fue razonablemente consistente.")
    if balance_score is not None and balance_score >= 70:
        positives.append("La mezcla de deportes y tipos de carga se ve aceptable para esta fase.")

    if flags.get("overload_flag"):
        risks.append("La carga semanal parece alta en comparacion con las semanas previas.")
    if flags.get("undertraining_flag"):
        risks.append("La semana quedo por debajo de la carga reciente o de lo planificado.")
    if flags.get("poor_distribution_flag"):
        risks.append("La carga quedo demasiado concentrada en pocos dias.")
    if flags.get("high_fatigue_risk_flag"):
        risks.append("La combinacion de carga y fatiga sugiere vigilar la recuperacion.")
    if flags.get("low_consistency_flag"):
        risks.append("La consistencia semanal fue baja.")

    duration_delta = trends.get("duration_vs_prev_avg_pct")
    if duration_delta is not None:
        findings.append(f"La duracion semanal quedo {duration_delta:+.1f}% vs el promedio reciente.")

    if not positives:
        positives.append("La semana deja una base util, aunque con informacion parcial en algunos frentes.")
    if not risks:
        risks.append("No aparecen alertas mayores, pero conviene confirmar la tendencia con otra semana similar.")
    dominant_issue = _detect_dominant_week_issue(flags)
    next_week_recommendation, recommendation_reason = _build_week_recommendation(dominant_issue, flags)
    if next_week_recommendation:
        recommendations.insert(0, next_week_recommendation)
    if not recommendations:
        recommendations.append(
            "Mantener la progresion y revisar si el objetivo principal de la semana siguiente pide ajustar volumen o intensidad."
        )

    summary_short = _weekly_summary_short(context, metrics, week_type)
    analysis_natural = _weekly_analysis_natural(context, metrics)
    coach_conclusion = _weekly_coach_conclusion(load_score, consistency_score, fatigue_score, week_type)
    next_week_recommendation = next_week_recommendation or recommendations[0]

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
        dominant_week_issue=dominant_issue,
        recommendation_reason=recommendation_reason,
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
    for field_name in (
        "summary_short",
        "analysis_natural",
        "coach_conclusion",
        "next_week_recommendation",
        "week_type_detected",
        "dominant_week_issue",
        "recommendation_reason",
    ):
        value = getattr(merged, field_name, None)
        if value is None:
            setattr(merged, field_name, getattr(fallback_output, field_name))
            continue
        if isinstance(value, str) and not value.strip():
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
    flags = metrics.get("derived_flags", {})
    distribution = metrics.get("distribution", {})
    fragments = [
        f"La semana tuvo {totals.get('activity_count', 0)} actividades y "
        f"{round((totals.get('total_duration_sec') or 0) / 3600.0, 1)} horas totales.",
        f"Los scores sugieren carga {round(scores.get('load_score') or 0)}, "
        f"consistencia {round(scores.get('consistency_score') or 0)}, "
        f"fatiga {round(scores.get('fatigue_score') or 0)} y balance {round(scores.get('balance_score') or 0)}.",
    ]
    if flags.get("intensity_distribution_imbalance_flag"):
        intensity_summary = distribution.get("intensity_zone_summary", {})
        pct_z2 = intensity_summary.get("pct_z2")
        pct_z4_plus = intensity_summary.get("pct_z4_plus")
        fragments.append(
            "La distribucion de intensidad quedo cargada en zonas altas"
            + (f" (Z2 {pct_z2}%, Z4+ {pct_z4_plus}%)" if pct_z2 is not None and pct_z4_plus is not None else ".")
        )
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
    if week_type == "intensidad_alta":
        return "La semana fue exigente por la alta proporción de intensidad, aunque el volumen no haya sido extremo."
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
    if flags.get("intensity_distribution_imbalance_flag"):
        return "intensidad_alta"
    if flags.get("overload_flag"):
        return "carga_excesiva"
    if flags.get("undertraining_flag"):
        return "carga_baja"
    if (scores.get("consistency_score") or 0) >= 70 and not flags.get("poor_distribution_flag"):
        return "consistente"
    return "mixta"


def _detect_dominant_week_issue(flags: Mapping[str, Any]) -> str | None:
    priority = [
        "intensity_distribution_imbalance_flag",
        "high_fatigue_risk_flag",
        "undertraining_flag",
        "overload_flag",
        "poor_distribution_flag",
        "low_consistency_flag",
    ]
    for flag in priority:
        if flags.get(flag):
            return flag.replace("_flag", "")
    return None


def _build_week_recommendation(
    dominant_issue: str | None,
    flags: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    if dominant_issue == "intensity_distribution_imbalance":
        return (
            "Bajar la intensidad relativa, recuperar base aerobica (Z1/Z2) y evitar acumular tantos minutos en Z3/Z4.",
            "Se detecto un desbalance de intensidad con exceso de carga en zonas altas.",
        )
    if dominant_issue == "high_fatigue_risk":
        return (
            "Priorizar una semana de descarga con sueno y recuperacion activa antes de volver a cargar.",
            "La combinacion de carga y senales de fatiga sugiere riesgo elevado.",
        )
    if dominant_issue == "undertraining":
        return (
            "Subir progresivamente volumen o frecuencia sin saltos bruscos, buscando regularidad.",
            "La semana quedo por debajo de la carga reciente o lo planificado.",
        )
    if dominant_issue == "overload":
        return (
            "Reducir la carga global y proteger dias suaves para evitar acumulacion de fatiga.",
            "La carga semanal fue alta respecto del contexto reciente.",
        )
    if dominant_issue == "poor_distribution":
        return (
            "Redistribuir mejor la carga entre dias para evitar concentraciones excesivas.",
            "La carga se concentro en pocos dias.",
        )
    if dominant_issue == "low_consistency":
        return (
            "Priorizar regularidad semanal antes de subir la carga total.",
            "La consistencia semanal fue baja.",
        )
    if flags:
        return (
            "Mantener la linea actual con ajustes finos segun el objetivo principal de la semana siguiente.",
            "No se detecto un problema dominante claro.",
        )
    return (
        "Mantener la progresion y revisar si el objetivo principal de la semana siguiente pide ajustar volumen o intensidad.",
        "No hay senales suficientes para una recomendacion mas especifica.",
    )


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
