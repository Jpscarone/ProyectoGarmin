from __future__ import annotations

import json
import logging
from statistics import mean
from typing import Any, Mapping

from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.services.openai_client import (
    OpenAIIntegrationError,
    build_openai_client,
    get_openai_max_output_tokens,
    get_openai_model,
)
from app.services.analysis_v2.schemas import NarrativeLLMOutput, NarrativeResult


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Sos un analista de entrenamiento de endurance para atletas amateurs avanzados.
Tu trabajo es interpretar una sesion planificada comparada con una actividad real.

Reglas obligatorias:
- Prioriza interpretacion util por sobre repetir numeros.
- No inventes datos ni asumas precision que no existe.
- Si faltan datos relevantes, reconocelo con prudencia.
- No hagas diagnosticos medicos ni afirmaciones clinicas.
- No uses markdown dentro de los campos.
- No agregues campos fuera del schema pedido.
- Devuelve siempre JSON estricto compatible con el schema.

Objetivos del analisis:
- explicar que tipo de sesion fue realmente
- evaluar si se cumplio el objetivo
- interpretar intensidad, control y fatiga
- contextualizar clima, fatiga y semana solo si realmente aportan
- cerrar con una recomendacion practica y accionable
""".strip()


def _is_truncated_json_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "json_invalid" in message
        or "eof while parsing" in message
        or "unterminated string" in message
        or "invalid json" in message
    )


def _session_token_attempts(settings: Settings) -> list[int]:
    configured = get_openai_max_output_tokens("session", settings)
    attempts = [configured]
    if configured < 1200:
        attempts.append(1200)
    if configured < 1500:
        attempts.append(1500)
    # Mantener orden y evitar duplicados.
    return list(dict.fromkeys(attempts))


def build_llm_payload(context: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    missing_data = _collect_missing_data(context, metrics)

    planned_vs_actual = metrics.get("planned_vs_actual", {})
    scores = metrics.get("scores", {})
    flags = metrics.get("derived_flags", {})
    comparisons = metrics.get("comparisons", {})
    weekly_context = metrics.get("weekly_context", {})
    laps = metrics.get("laps", {})
    heart_rate = metrics.get("heart_rate")
    pace = metrics.get("pace")
    power = metrics.get("power")
    cadence = metrics.get("cadence")
    intensity = metrics.get("intensity")

    return {
        "athlete_profile": {
            "name": context.athlete.name,
            "primary_sport": context.athlete.primary_sport,
            "max_hr": context.athlete.max_hr,
            "resting_hr": context.athlete.resting_hr,
            "running_threshold_pace_sec_km": context.athlete.running_threshold_pace_sec_km,
            "cycling_ftp": context.athlete.cycling_ftp,
            "vo2max": context.athlete.vo2max,
        },
        "planned_session": {
            "date": _iso(context.planned_session.session_date),
            "title": context.planned_session.title,
            "sport_type": context.planned_session.sport_type,
            "discipline_variant": context.planned_session.discipline_variant,
            "session_type": context.planned_session.session_type,
            "description": context.planned_session.description,
            "target_notes": context.planned_session.target_notes,
            "expected_duration_min": context.planned_session.expected_duration_min,
            "expected_distance_km": context.planned_session.expected_distance_km,
            "expected_elevation_gain_m": context.planned_session.expected_elevation_gain_m,
            "target_type": context.planned_session.target_type,
            "target_hr_zone": context.planned_session.target_hr_zone,
            "target_pace_zone": context.planned_session.target_pace_zone,
            "target_power_zone": context.planned_session.target_power_zone,
            "target_rpe_zone": context.planned_session.target_rpe_zone,
            "goal": {
                "name": context.planned_session.goal.name,
                "role": context.planned_session.goal.role,
                "event_date": _iso(context.planned_session.goal.event_date),
                "distance_km": context.planned_session.goal.distance_km,
                "priority": context.planned_session.goal.priority,
            } if context.planned_session.goal else None,
            "steps": [
                {
                    "order": step.order,
                    "step_type": step.step_type,
                    "repeat_count": step.repeat_count,
                    "duration_sec": step.duration_sec,
                    "distance_m": step.distance_m,
                    "target_type": step.target_type,
                    "target_hr_zone": step.target_hr_zone,
                    "target_pace_zone": step.target_pace_zone,
                    "target_power_zone": step.target_power_zone,
                    "target_rpe_zone": step.target_rpe_zone,
                    "target_notes": step.target_notes,
                }
                for step in context.planned_session.steps[:20]
            ],
        },
        "actual_activity": {
            "date": _iso(context.activity.local_date),
            "start_time": context.activity.start_time,
            "title": context.activity.title,
            "sport_type": context.activity.sport_type,
            "discipline_variant": context.activity.discipline_variant,
            "duration_sec": context.activity.duration_sec,
            "moving_duration_sec": context.activity.moving_duration_sec,
            "distance_m": context.activity.distance_m,
            "elevation_gain_m": context.activity.elevation_gain_m,
            "avg_hr": context.activity.avg_hr,
            "max_hr": context.activity.max_hr,
            "avg_pace_sec_km": context.activity.avg_pace_sec_km,
            "avg_power": context.activity.avg_power,
            "avg_cadence": context.activity.avg_cadence,
            "calories": context.activity.calories,
            "training_effect_aerobic": context.activity.training_effect_aerobic,
            "training_effect_anaerobic": context.activity.training_effect_anaerobic,
            "training_load": context.activity.training_load,
            "temperature_c": context.activity.avg_temperature_c,
        },
        "lap_summary": {
            "lap_count": len(context.activity_laps),
            "matched_count": laps.get("matched_count"),
            "missing_planned_steps": laps.get("missing_planned_steps"),
            "extra_laps": laps.get("extra_laps"),
            "alignment_score": laps.get("alignment_score"),
            "comparisons": (laps.get("comparisons") or [])[:10],
        },
        "weather": {
            "temperature_c": context.weather.temperature_c,
            "humidity_pct": context.weather.humidity_pct,
            "wind_speed_kmh": context.weather.wind_speed_kmh,
            "precipitation_total_mm": context.weather.precipitation_total_mm,
            "condition_text": context.weather.condition_text,
        } if context.weather else None,
        "health": {
            "metric_date": _iso(context.health.metric_date),
            "sleep_hours": context.health.sleep_hours,
            "sleep_score": context.health.sleep_score,
            "hrv_status": context.health.hrv_status,
            "hrv_avg_ms": context.health.hrv_avg_ms,
            "body_battery_start": context.health.body_battery_start,
            "body_battery_end": context.health.body_battery_end,
            "stress_avg": context.health.stress_avg,
            "recovery_time_hours": context.health.recovery_time_hours,
            "resting_hr": context.health.resting_hr,
        } if context.health else None,
        "key_metrics": {
            "planned_vs_actual": planned_vs_actual,
            "heart_rate": heart_rate,
            "pace": pace,
            "power": power,
            "cadence": cadence,
            "intensity": intensity,
            "scores": scores,
            "derived_flags": flags,
        },
        "recent_similar_sessions": [
            {
                "date": _iso(item.date),
                "title": item.title,
                "sport_type": item.sport_type,
                "duration_sec": item.duration_sec,
                "distance_m": item.distance_m,
                "elevation_gain_m": item.elevation_gain_m,
                "avg_hr": item.avg_hr,
                "avg_pace_sec_km": item.avg_pace_sec_km,
                "analysis_summary": item.analysis_summary,
            }
            for item in context.recent_similar_sessions[:3]
        ],
        "weekly_context": weekly_context,
        "comparisons": comparisons,
        "missing_data": missing_data,
    }


def generate_session_narrative(context: Any, metrics: Mapping[str, Any]) -> NarrativeResult:
    settings = get_settings()
    payload = build_llm_payload(context, metrics)
    payload_json = json.dumps(payload, ensure_ascii=False)
    fallback_output = _build_fallback_output(context, metrics)

    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY no configurada. Se usa narrativa fallback para SessionAnalysis V2.")
        return NarrativeResult.from_llm_output(
            fallback_output,
            narrative_status="skipped_no_api_key",
            provider=None,
            model=None,
            llm_json={
                "provider": None,
                "model": None,
                "status": "skipped_no_api_key",
                "narrative_status": "skipped_no_api_key",
                "payload": payload,
                "structured_output": fallback_output.to_structured_output().model_dump(),
            },
            error_message="OPENAI_API_KEY no configurada.",
        )

    model = get_openai_model(settings)
    try:
        client = build_openai_client(settings)
    except OpenAIIntegrationError:
        logger.warning("No se pudo construir el cliente OpenAI. Se usa narrativa fallback.")
        return NarrativeResult.from_llm_output(
            fallback_output,
            narrative_status="error",
            provider="openai",
            model=model,
            llm_json={
                "provider": "openai",
                "model": model,
                "status": "client_unavailable",
                "narrative_status": "error",
                "payload": payload,
                "structured_output": fallback_output.to_structured_output().model_dump(),
            },
            error_message="No se pudo inicializar el cliente OpenAI.",
        )

    try:
        last_parse_exc: Exception | None = None
        token_attempts = _session_token_attempts(settings)
        for max_output_tokens in token_attempts:
            try:
                response = client.responses.parse(
                    model=model,
                    instructions=SYSTEM_PROMPT,
                    input=payload_json,
                    text_format=NarrativeLLMOutput,
                    temperature=0.3,
                    max_output_tokens=max_output_tokens,
                    timeout=settings.openai_timeout_sec,
                )
                parsed = response.output_parsed
                if parsed is None:
                    raise ValueError("OpenAI no devolvio salida parseada.")
                llm_output = parsed if isinstance(parsed, NarrativeLLMOutput) else NarrativeLLMOutput.model_validate(parsed)
                llm_output = _merge_llm_output_with_fallback(llm_output, fallback_output)
                llm_json = {
                    "provider": "openai",
                    "model": model,
                    "status": "completed",
                    "narrative_status": "completed",
                    "response_id": getattr(response, "id", None),
                    "usage": _response_usage_to_dict(getattr(response, "usage", None)),
                    "payload": payload,
                    "max_output_tokens_used": max_output_tokens,
                    "structured_output": llm_output.to_structured_output().model_dump(),
                }
                return NarrativeResult.from_llm_output(
                    llm_output,
                    narrative_status="completed",
                    provider="openai",
                    model=model,
                    llm_json=llm_json,
                )
            except (ValidationError, ValueError) as exc:
                last_parse_exc = exc
                if _is_truncated_json_error(exc) and max_output_tokens != token_attempts[-1]:
                    logger.warning(
                        "Respuesta estructurada de OpenAI truncada para SessionAnalysis; se reintenta con mas tokens. model=%s tokens=%s error=%s",
                        model,
                        max_output_tokens,
                        exc,
                    )
                    continue
                raise
        if last_parse_exc is not None:
            raise last_parse_exc
        raise ValueError("OpenAI no devolvio una narrativa utilizable.")
    except (RateLimitError, APITimeoutError, APIConnectionError, APIError, ValidationError, ValueError) as exc:
        logger.exception("Fallo generate_session_narrative con OpenAI; se usa fallback.")
        status = "error"
        if isinstance(exc, RateLimitError):
            status = "rate_limited"
        elif isinstance(exc, APITimeoutError):
            status = "timeout"

        return NarrativeResult.from_llm_output(
            fallback_output,
            narrative_status=status,
            provider="openai",
            model=model,
            llm_json={
                "provider": "openai",
                "model": model,
                "status": status,
                "narrative_status": status,
                "payload": payload,
                "structured_output": fallback_output.to_structured_output().model_dump(),
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
            error_message=str(exc),
        )
    except Exception as exc:  # pragma: no cover - ultima linea defensiva
        logger.exception("Error inesperado en generate_session_narrative; se usa fallback.")
        return NarrativeResult.from_llm_output(
            fallback_output,
            narrative_status="error",
            provider="openai",
            model=model,
            llm_json={
                "provider": "openai",
                "model": model,
                "status": "error",
                "narrative_status": "error",
                "payload": payload,
                "structured_output": fallback_output.to_structured_output().model_dump(),
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
            error_message=str(exc),
        )


def _build_fallback_output(context: Any, metrics: Mapping[str, Any]) -> NarrativeLLMOutput:
    scores = metrics.get("scores", {})
    compliance = scores.get("compliance_score")
    execution = scores.get("execution_score")
    control = scores.get("control_score")
    fatigue = scores.get("fatigue_score")
    flags = metrics.get("derived_flags", {})
    planned_vs_actual = metrics.get("planned_vs_actual", {})
    recent = metrics.get("comparisons", {}).get("recent_similar", {})
    weekly_context = metrics.get("weekly_context", {})

    session_type_detected = (
        context.planned_session.session_type
        or context.planned_session.target_type
        or context.planned_session.sport_type
        or "indeterminada"
    )
    overall_assessment = _overall_assessment_label(compliance, execution, flags)

    positives: list[str] = []
    risks: list[str] = []
    recommendations: list[str] = []
    tags: list[str] = [context.planned_session.sport_type or "sin_deporte", overall_assessment]

    duration_ratio = _ratio_to_pct(planned_vs_actual.get("duration", {}).get("actual_to_planned_ratio"))
    distance_ratio = _ratio_to_pct(planned_vs_actual.get("distance", {}).get("actual_to_planned_ratio"))

    if duration_ratio is not None:
        if 90 <= duration_ratio <= 110:
            positives.append("La duracion quedo cerca de lo planificado.")
        elif duration_ratio < 85:
            risks.append("La duracion quedo claramente por debajo de lo previsto.")
        elif duration_ratio > 115:
            risks.append("La duracion se fue por encima de lo planificado.")

    if distance_ratio is not None:
        if 90 <= distance_ratio <= 110:
            positives.append("La distancia estuvo alineada con el objetivo.")
        elif distance_ratio < 85:
            risks.append("La distancia realizada quedo corta frente a lo planeado.")
        elif distance_ratio > 115:
            risks.append("La distancia supero con claridad el objetivo previsto.")

    if flags.get("heart_rate_high_flag"):
        risks.append("La frecuencia cardiaca media quedo alta para el contexto disponible.")
        recommendations.append("Revisar si el control de intensidad fue el adecuado para el objetivo de la sesion.")
        tags.append("fc_alta")
    if flags.get("pace_instability_flag"):
        risks.append("El ritmo mostro variabilidad relevante entre laps.")
        recommendations.append("Buscar una ejecucion mas estable si la sesion apuntaba a control aerobico o tempo sostenido.")
        tags.append("ritmo_inestable")
    if flags.get("heat_impact_flag"):
        risks.append("El contexto de temperatura pudo influir en la percepcion y el control de la carga.")
        recommendations.append("Ajustar hidratacion y expectativas de ritmo cuando el calor sube.")
        tags.append("calor")
    if flags.get("hydration_risk_flag"):
        risks.append("La combinacion de duracion y temperatura sugiere un riesgo de hidratacion a vigilar.")
        tags.append("hidratacion")
    if flags.get("cardiac_drift_flag"):
        risks.append("Aparecen indicios de deriva cardiaca con estabilidad de ritmo razonable.")
        tags.append("drift_cardiaco")

    if recent:
        duration_delta = recent.get("duration_vs_recent_avg_pct")
        if duration_delta is not None and abs(duration_delta) >= 10:
            if duration_delta > 0:
                positives.append("La sesion fue mas extensa que el promedio reciente comparable.")
            else:
                risks.append("La sesion quedo por debajo del promedio reciente comparable.")

    activity_count = weekly_context.get("activity_count")
    if activity_count:
        positives.append(f"Esta sesion se inserta en una semana con {activity_count} actividades registradas.")

    if not recommendations:
        recommendations.append("Usar esta lectura como referencia y confirmar el patron en las proximas sesiones similares.")

    if not positives:
        positives.append("No hay desajustes graves evidentes en los datos disponibles.")
    if not risks:
        risks.append("No aparecen riesgos claros con los datos disponibles, aunque faltan algunas capas de contexto.")

    summary_short = _build_summary_short(context, planned_vs_actual, overall_assessment)
    analysis_natural = _build_analysis_natural(
        context=context,
        compliance=compliance,
        execution=execution,
        control=control,
        fatigue=fatigue,
        flags=flags,
        planned_vs_actual=planned_vs_actual,
        weekly_context=weekly_context,
    )
    coach_conclusion = _build_coach_conclusion(compliance, execution, control, overall_assessment)
    next_recommendation = recommendations[0]

    interpretive_flags = {
        "duration_over_target_flag": bool(flags.get("duration_over_target_flag")),
        "distance_over_target_flag": bool(flags.get("distance_over_target_flag")),
        "elevation_over_target_flag": bool(flags.get("elevation_over_target_flag")),
        "heart_rate_high_flag": bool(flags.get("heart_rate_high_flag")),
        "pace_instability_flag": bool(flags.get("pace_instability_flag")),
        "possible_heat_impact_flag": bool(flags.get("possible_heat_impact_flag")),
        "heat_impact_flag": bool(flags.get("heat_impact_flag")),
        "cardiac_drift_flag": bool(flags.get("cardiac_drift_flag")),
        "hydration_risk_flag": bool(flags.get("hydration_risk_flag")),
        "manual_review_needed": bool(flags.get("manual_review_needed")),
    }

    return NarrativeLLMOutput(
        summary_short=summary_short,
        analysis_natural=analysis_natural,
        coach_conclusion=coach_conclusion,
        next_recommendation=next_recommendation,
        session_type_detected=session_type_detected,
        overall_assessment=overall_assessment,
        key_positive_points=positives[:4],
        key_risk_points=risks[:4],
        practical_recommendations=recommendations[:4],
        tags=_unique_items(tags)[:6],
        interpretive_flags=interpretive_flags,
    )


def _merge_llm_output_with_fallback(
    llm_output: NarrativeLLMOutput,
    fallback_output: NarrativeLLMOutput,
) -> NarrativeLLMOutput:
    merged = llm_output.model_copy(deep=True)

    for field_name in ("summary_short", "analysis_natural", "coach_conclusion", "next_recommendation"):
        if not getattr(merged, field_name, "").strip():
            setattr(merged, field_name, getattr(fallback_output, field_name))

    for field_name in ("session_type_detected", "overall_assessment"):
        if not getattr(merged, field_name, "").strip():
            setattr(merged, field_name, getattr(fallback_output, field_name))

    for field_name in ("key_positive_points", "key_risk_points", "practical_recommendations", "tags"):
        if not getattr(merged, field_name):
            setattr(merged, field_name, list(getattr(fallback_output, field_name)))

    if not merged.interpretive_flags:
        merged.interpretive_flags = fallback_output.interpretive_flags.model_copy(deep=True)

    return merged


def _build_summary_short(context: Any, planned_vs_actual: Mapping[str, Any], overall_assessment: str) -> str:
    bits = [f"Sesion {overall_assessment}"]
    sport = context.planned_session.sport_type
    if sport:
        bits.append(f"de {sport}")

    duration_ratio = _ratio_to_pct(planned_vs_actual.get("duration", {}).get("actual_to_planned_ratio"))
    distance_ratio = _ratio_to_pct(planned_vs_actual.get("distance", {}).get("actual_to_planned_ratio"))
    if duration_ratio is not None:
        bits.append(f"duracion al {round(duration_ratio)}%")
    if distance_ratio is not None:
        bits.append(f"distancia al {round(distance_ratio)}%")
    return ", ".join(bits) + "."


def _build_analysis_natural(
    *,
    context: Any,
    compliance: float | None,
    execution: float | None,
    control: float | None,
    fatigue: float | None,
    flags: Mapping[str, Any],
    planned_vs_actual: Mapping[str, Any],
    weekly_context: Mapping[str, Any],
) -> str:
    fragments: list[str] = []
    fragments.append(
        f"La sesion planificada fue de {context.planned_session.sport_type or 'deporte no especificado'} "
        f"y la actividad real quedo vinculada sin indicios de cambio de deporte."
    )

    duration_ratio = _ratio_to_pct(planned_vs_actual.get("duration", {}).get("actual_to_planned_ratio"))
    distance_ratio = _ratio_to_pct(planned_vs_actual.get("distance", {}).get("actual_to_planned_ratio"))
    if duration_ratio is not None or distance_ratio is not None:
        duration_text = f"duracion al {round(duration_ratio)}%" if duration_ratio is not None else "duracion no evaluable"
        distance_text = f"distancia al {round(distance_ratio)}%" if distance_ratio is not None else "distancia no evaluable"
        fragments.append(f"En cumplimiento basico, quedo con {duration_text} y {distance_text}.")

    score_bits: list[str] = []
    if compliance is not None:
        score_bits.append(f"cumplimiento {round(compliance)}")
    if execution is not None:
        score_bits.append(f"ejecucion {round(execution)}")
    if control is not None:
        score_bits.append(f"control {round(control)}")
    if fatigue is not None:
        score_bits.append(f"fatiga {round(fatigue)}")
    if score_bits:
        fragments.append("Los scores sugieren " + ", ".join(score_bits) + ".")

    contextual_notes: list[str] = []
    if flags.get("heart_rate_high_flag"):
        contextual_notes.append("la frecuencia cardiaca quedo relativamente alta")
    if flags.get("pace_instability_flag"):
        contextual_notes.append("hubo variabilidad de ritmo")
    if flags.get("heat_impact_flag"):
        contextual_notes.append("el calor pudo influir en la respuesta")
    if flags.get("cardiac_drift_flag"):
        contextual_notes.append("aparecen signos de deriva cardiaca")
    if contextual_notes:
        fragments.append("En la interpretacion del esfuerzo, " + ", ".join(contextual_notes) + ".")

    activity_count = weekly_context.get("activity_count")
    total_duration_sec = weekly_context.get("total_duration_sec")
    if activity_count and total_duration_sec:
        weekly_hours = round(total_duration_sec / 3600.0, 1)
        fragments.append(
            f"Dentro de la semana actual, esta sesion se apoya en una carga acumulada de {activity_count} actividades y {weekly_hours} horas."
        )

    return " ".join(fragments)


def _build_coach_conclusion(
    compliance: float | None,
    execution: float | None,
    control: float | None,
    overall_assessment: str,
) -> str:
    if overall_assessment == "cumplida":
        return "La sesion quedo bien encaminada y suma como trabajo util dentro del plan."
    if overall_assessment == "parcial":
        return "La sesion aporta, pero no replica del todo el estimulo planeado y conviene leerla como cumplimiento parcial."
    if overall_assessment == "desviada":
        return "La sesion se alejo del objetivo previsto y merece revisarse antes de tomarla como equivalente."
    if compliance is not None and execution is not None and control is not None:
        return (
            "La lectura general queda en revision: el cumplimiento, la ejecucion y el control no terminan de alinearse "
            "de forma concluyente con la intencion original."
        )
    return "La lectura queda en revision por datos incompletos o senales mixtas."


def _overall_assessment_label(
    compliance_score: float | None,
    execution_score: float | None,
    flags: Mapping[str, Any],
) -> str:
    if flags.get("manual_review_needed"):
        return "revision"
    average = _mean_known([compliance_score, execution_score])
    if average is None:
        return "revision"
    if average >= 85:
        return "cumplida"
    if average >= 65:
        return "parcial"
    return "desviada"


def _collect_missing_data(context: Any, metrics: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    if context.activity.avg_hr is None:
        missing.append("Sin frecuencia cardiaca media.")
    if context.activity.avg_pace_sec_km is None:
        missing.append("Sin ritmo medio.")
    if context.activity.avg_power is None:
        missing.append("Sin potencia media.")
    if not context.activity_laps:
        missing.append("Sin laps o splits reales.")
    if context.weather is None:
        missing.append("Sin contexto de clima.")
    if context.health is None:
        missing.append("Sin contexto de salud cercano.")
    if not context.recent_similar_sessions:
        missing.append("Sin sesiones recientes comparables.")
    if metrics.get("heart_rate") is None:
        missing.append("Sin bloque interpretable de frecuencia cardiaca.")
    return missing


def _response_usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {"value": str(usage)}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _ratio_to_pct(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value) * 100.0
    except (TypeError, ValueError):
        return None


def _mean_known(values: list[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return mean(usable)


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
