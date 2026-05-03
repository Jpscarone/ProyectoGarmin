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

WEATHER_HEAT_THRESHOLD_C = 28.0
WEATHER_HUMIDITY_THRESHOLD_PCT = 75.0
WEATHER_WIND_THRESHOLD_KMH = 25.0
WEATHER_PRECIP_THRESHOLD_MM = 1.0
WEATHER_COLD_THRESHOLD_C = 5.0

HEALTH_SLEEP_HOURS_LOW = 6.0
HEALTH_SLEEP_HOURS_MODERATE = 6.75
HEALTH_SLEEP_SCORE_LOW = 60
HEALTH_SLEEP_SCORE_MODERATE = 70
HEALTH_STRESS_HIGH = 40
HEALTH_STRESS_MODERATE = 30
HEALTH_BODY_BATTERY_LOW = 40
HEALTH_BODY_BATTERY_MODERATE = 55
HEALTH_RECOVERY_TIME_HIGH_HOURS = 24.0
HEALTH_RECOVERY_TIME_MODERATE_HOURS = 18.0

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

Uso del contexto:
- Si contextual_factors.has_relevant_context es false, no menciones clima ni estado general como relleno.
- Si hay contexto relevante, usalo solo para matizar la lectura, no como excusa automatica.
- No atribuyas todos los problemas al clima o al estado general sin evidencia en los datos.
- No inventes sensaciones subjetivas del atleta.

Reglas de interpretacion de pace:
- Si el ritmo real es mas rapido que el rango objetivo, la intensidad fue mas exigente (no "por debajo").
- Si el ritmo real es mas lento que el rango objetivo, la intensidad fue menor (por debajo del objetivo).
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
    relevant_context = build_relevant_context_for_llm(context, metrics)

    planned_vs_actual = metrics.get("planned_vs_actual", {})
    scores = metrics.get("scores", {})
    flags = metrics.get("derived_flags", {})
    comparisons = metrics.get("comparisons", {})
    weekly_context = metrics.get("weekly_context", {})
    laps = metrics.get("laps", {})
    structure = metrics.get("structure", {})
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
            "structural_confidence": (laps.get("structured_match") or {}).get("structural_confidence"),
            "interval_structure_detected": (laps.get("structured_match") or {}).get("interval_structure_detected"),
            "unmatched_laps": (laps.get("structured_match") or {}).get("unmatched_laps"),
            "unmatched_steps": (laps.get("structured_match") or {}).get("unmatched_steps"),
            "comparisons": (laps.get("comparisons") or [])[:10],
        },
        "session_structure": {
            "session_intent": metrics.get("session_intent"),
            "primary_targets": structure.get("primary_targets"),
            "block_structure": structure.get("block_structure"),
            "expected_repeats_summary": structure.get("expected_repeats_summary"),
            "block_analysis": metrics.get("block_analysis", [])[:20],
        },
        "contextual_factors": relevant_context,
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
        return _build_narrative_result(
            context,
            metrics,
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
        return _build_narrative_result(
            context,
            metrics,
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
                return _build_narrative_result(
                    context,
                    metrics,
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

        return _build_narrative_result(
            context,
            metrics,
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
        return _build_narrative_result(
            context,
            metrics,
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


def _build_narrative_result(
    context: Any,
    metrics: Mapping[str, Any],
    output: NarrativeLLMOutput,
    *,
    narrative_status: str,
    provider: str | None,
    model: str | None,
    llm_json: dict[str, Any],
    error_message: str | None = None,
) -> NarrativeResult:
    quick_takeaway = _build_quick_takeaway(context, metrics, output)
    enriched_llm_json = {
        **llm_json,
        "quick_takeaway": quick_takeaway,
        "quick_takeaway_source": "rule_based_v1",
    }
    return NarrativeResult.from_llm_output(
        output,
        narrative_status=narrative_status,
        provider=provider,
        model=model,
        llm_json=enriched_llm_json,
        quick_takeaway=quick_takeaway,
        error_message=error_message,
    )


def build_analysis_context_flags(context: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    weather_context = build_weather_context_summary(getattr(context, "weather", None), metrics)
    health_context = build_health_context_summary(getattr(context, "health", None), metrics)
    combined_parts = [part for part in (weather_context["summary"], health_context["summary"]) if part]
    return {
        "weather_relevant": weather_context["relevant"],
        "health_relevant": health_context["relevant"],
        "weather_signals": weather_context["signals"],
        "health_signals": health_context["signals"],
        "combined_summary": " ".join(combined_parts) if combined_parts else None,
    }


def build_weather_context_summary(weather: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    if weather is None:
        return {"relevant": False, "summary": None, "signals": []}

    derived_flags = metrics.get("derived_flags", {}) if isinstance(metrics, Mapping) else {}
    signals: list[str] = []
    detail_parts: list[str] = []

    effective_temp = _first_number(getattr(weather, "apparent_temperature_c", None), getattr(weather, "temperature_c", None))
    if effective_temp is not None and effective_temp >= WEATHER_HEAT_THRESHOLD_C:
        signals.append("calor")
        detail_parts.append(f"temperatura alta (~{round(effective_temp)}°C)")
    elif effective_temp is not None and effective_temp <= WEATHER_COLD_THRESHOLD_C:
        signals.append("frio")
        detail_parts.append(f"frio marcado (~{round(effective_temp)}°C)")

    humidity = getattr(weather, "humidity_pct", None)
    if humidity is not None and humidity >= WEATHER_HUMIDITY_THRESHOLD_PCT:
        signals.append("humedad_alta")
        detail_parts.append(f"humedad alta (~{round(humidity)}%)")

    wind_speed = getattr(weather, "wind_speed_kmh", None)
    if wind_speed is not None and wind_speed >= WEATHER_WIND_THRESHOLD_KMH:
        signals.append("viento_fuerte")
        detail_parts.append(f"viento fuerte (~{round(wind_speed)} km/h)")

    precipitation = _first_number(
        getattr(weather, "precipitation_total_mm", None),
        getattr(weather, "precipitation_mm", None),
    )
    if precipitation is not None and precipitation >= WEATHER_PRECIP_THRESHOLD_MM:
        signals.append("lluvia")
        detail_parts.append(f"precipitacion relevante (~{round(precipitation, 1)} mm)")

    if not detail_parts:
        return {"relevant": False, "summary": None, "signals": []}

    effect_parts: list[str] = []
    if derived_flags.get("heat_impact_flag") or derived_flags.get("hydration_risk_flag"):
        effect_parts.append("puede haber elevado la frecuencia cardiaca o la carga fisiologica")
    if derived_flags.get("pace_instability_flag") and wind_speed is not None and wind_speed >= WEATHER_WIND_THRESHOLD_KMH:
        effect_parts.append("puede haber encarecido el control del ritmo")
    if not effect_parts:
        effect_parts.append("puede haber matizado la lectura del esfuerzo")

    summary = (
        f"La sesion se realizo con {', '.join(detail_parts)}, un contexto que "
        f"{' y '.join(effect_parts)}."
    )
    return {"relevant": True, "summary": summary, "signals": signals}


def build_health_context_summary(health: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    if health is None:
        return {"relevant": False, "summary": None, "signals": []}

    signals: list[str] = []
    critical = False
    moderate_signals = 0

    sleep_hours = getattr(health, "sleep_hours", None)
    sleep_score = getattr(health, "sleep_score", None)
    hrv_status = getattr(health, "hrv_status", None)
    stress_avg = getattr(health, "stress_avg", None)
    body_battery_start = getattr(health, "body_battery_start", None)
    recovery_time_hours = getattr(health, "recovery_time_hours", None)

    if sleep_hours is not None:
        if sleep_hours < HEALTH_SLEEP_HOURS_LOW:
            signals.append(f"sueño bajo ({sleep_hours:.1f} h)")
            critical = True
        elif sleep_hours < HEALTH_SLEEP_HOURS_MODERATE:
            signals.append(f"sueño algo corto ({sleep_hours:.1f} h)")
            moderate_signals += 1

    if sleep_score is not None:
        if sleep_score < HEALTH_SLEEP_SCORE_LOW:
            signals.append(f"sleep score bajo ({sleep_score})")
            critical = True
        elif sleep_score < HEALTH_SLEEP_SCORE_MODERATE:
            signals.append(f"sleep score algo bajo ({sleep_score})")
            moderate_signals += 1

    if _is_low_hrv_status(hrv_status):
        signals.append(f"HRV {hrv_status}")
        critical = True

    if stress_avg is not None:
        if stress_avg >= HEALTH_STRESS_HIGH:
            signals.append(f"estres alto ({stress_avg})")
            critical = True
        elif stress_avg >= HEALTH_STRESS_MODERATE:
            signals.append(f"estres moderado-alto ({stress_avg})")
            moderate_signals += 1

    if body_battery_start is not None:
        if body_battery_start < HEALTH_BODY_BATTERY_LOW:
            signals.append(f"body battery baja ({body_battery_start})")
            critical = True
        elif body_battery_start < HEALTH_BODY_BATTERY_MODERATE:
            signals.append(f"body battery algo baja ({body_battery_start})")
            moderate_signals += 1

    if recovery_time_hours is not None:
        if recovery_time_hours >= HEALTH_RECOVERY_TIME_HIGH_HOURS:
            signals.append(f"recuperacion alta pendiente ({round(recovery_time_hours)} h)")
            critical = True
        elif recovery_time_hours >= HEALTH_RECOVERY_TIME_MODERATE_HOURS:
            signals.append(f"recuperacion todavia exigente ({round(recovery_time_hours)} h)")
            moderate_signals += 1

    relevant = critical or moderate_signals >= 2
    if not relevant:
        return {"relevant": False, "summary": None, "signals": []}

    scores = metrics.get("scores", {}) if isinstance(metrics, Mapping) else {}
    control_score = scores.get("control_score")
    fatigue_score = scores.get("fatigue_score")
    effect_parts: list[str] = []
    if fatigue_score is not None and fatigue_score >= 65:
        effect_parts.append("puede haber aumentado el costo fisiologico")
    if control_score is not None and control_score < 75:
        effect_parts.append("puede haber afectado el control del esfuerzo")
    if not effect_parts:
        effect_parts.append("puede haber condicionado la disponibilidad del dia")

    summary = (
        f"El atleta llegaba con señales de fatiga o recuperacion incompleta ({', '.join(signals)}), "
        f"lo que {' y '.join(effect_parts)}."
    )
    return {"relevant": True, "summary": summary, "signals": signals}


def build_relevant_context_for_llm(context: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    weather_context = build_weather_context_summary(getattr(context, "weather", None), metrics)
    health_context = build_health_context_summary(getattr(context, "health", None), metrics)
    flags = build_analysis_context_flags(context, metrics)
    return {
        "has_relevant_context": bool(flags["weather_relevant"] or flags["health_relevant"]),
        "weather_relevant": flags["weather_relevant"],
        "health_relevant": flags["health_relevant"],
        "weather_summary": weather_context["summary"],
        "health_summary": health_context["summary"],
        "summary": flags["combined_summary"],
    }


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
    if flags.get("recovery_block_not_effective_flag"):
        risks.insert(0, "Las recuperaciones quedaron altas y no permitieron volver a la zona objetivo.")
        recommendations.insert(0, "Bajar la intensidad en las recuperaciones para asegurar el regreso a Z2.")
        tags.append("recuperacion_alta")
    if flags.get("work_block_under_target_flag"):
        risks.insert(0, "Los bloques de trabajo quedaron por debajo del objetivo planificado.")
        recommendations.insert(0, "Buscar sostener el ritmo objetivo en los bloques de trabajo.")
        tags.append("trabajo_bajo")
    if flags.get("work_block_over_target_flag"):
        risks.insert(0, "Los bloques de trabajo quedaron por encima del objetivo planificado.")
        recommendations.insert(0, "Controlar el ritmo para no exceder la zona objetivo en los bloques clave.")
        tags.append("trabajo_alto")
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


def _build_quick_takeaway(
    context: Any,
    metrics: Mapping[str, Any],
    output: NarrativeLLMOutput,
) -> str:
    scores = metrics.get("scores", {})
    flags = metrics.get("derived_flags", {})
    heart_rate = metrics.get("heart_rate") or {}
    pace = metrics.get("pace") or {}
    cadence = metrics.get("cadence") or {}
    weekly_context = metrics.get("weekly_context") or {}
    recent = (metrics.get("comparisons") or {}).get("recent_similar") or {}
    block_analysis = metrics.get("block_analysis") or []
    session_intent = metrics.get("session_intent")
    dominant_issue = _quick_takeaway_dominant_issue(flags, scores, block_analysis)
    days_to_goal = _days_to_goal(context)
    is_pre_race = days_to_goal is not None and 0 <= days_to_goal <= 10
    session_family = _quick_takeaway_session_family(session_intent, is_pre_race)
    severity = _quick_takeaway_contextual_severity(
        dominant_issue=dominant_issue,
        session_family=session_family,
        flags=flags,
        scores=scores,
        metrics=metrics,
        is_pre_race=is_pre_race,
    )

    opener = _quick_takeaway_opener(
        overall=output.overall_assessment or "mixta",
        session_family=session_family,
        dominant_issue=dominant_issue,
        severity=severity,
        compliance=scores.get("compliance_score"),
        execution=scores.get("execution_score"),
        control=scores.get("control_score"),
        fatigue=scores.get("fatigue_score"),
        weekly_context=weekly_context,
        is_pre_race=is_pre_race,
    )
    strengths = _quick_takeaway_strengths(
        session_family=session_family,
        heart_rate=heart_rate,
        cadence=cadence,
        control=scores.get("control_score"),
        flags=flags,
        recent=recent,
        is_pre_race=is_pre_race,
    )
    caution = _quick_takeaway_caution(
        dominant_issue=dominant_issue,
        session_family=session_family,
        severity=severity,
        flags=flags,
        block_analysis=block_analysis,
        heart_rate=heart_rate,
        pace=pace,
        fatigue=scores.get("fatigue_score"),
        is_pre_race=is_pre_race,
    )
    learning = _quick_takeaway_learning(
        dominant_issue=dominant_issue,
        session_family=session_family,
        severity=severity,
        flags=flags,
        block_analysis=block_analysis,
        metrics=metrics,
        context=context,
        is_pre_race=is_pre_race,
        days_to_goal=days_to_goal,
    )

    paragraphs: list[str] = [opener]
    second_paragraph: list[str] = []
    if strengths:
        second_paragraph.append("Lo mas rescatable fue " + _join_phrases(strengths[:3]) + ".")
    if caution:
        second_paragraph.append(caution)
    if learning:
        second_paragraph.append(learning)
    if second_paragraph:
        paragraphs.append(" ".join(second_paragraph))
    return "\n\n".join(part for part in paragraphs if part).strip()


def _quick_takeaway_opener(
    *,
    overall: str,
    session_family: str,
    dominant_issue: str | None,
    severity: str,
    compliance: float | None,
    execution: float | None,
    control: float | None,
    fatigue: float | None,
    weekly_context: Mapping[str, Any],
    is_pre_race: bool,
) -> str:
    weekly_context_note = ""
    activity_count = weekly_context.get("activity_count")
    if activity_count:
        weekly_context_note = f" dentro de una semana con {activity_count} actividades"

    if is_pre_race and severity == "low" and (dominant_issue is None or dominant_issue in {"work_over_target", "recovery_not_effective"}):
        return f"Para una sesion tan cerca de carrera, la lectura es buena{weekly_context_note}: hubo activacion sin dejar una carga innecesaria."
    if dominant_issue == "recovery_not_effective":
        if severity == "low":
            return f"Lo mas flojo estuvo en las recuperaciones{weekly_context_note}, aunque sin una senal clara de que la sesion se haya ido de las manos."
        if severity == "moderate":
            return f"Lo que quedo flojo no fue el trabajo, sino la recuperacion entre bloques{weekly_context_note}."
        return f"La recuperacion entre bloques quedo demasiado corta{weekly_context_note} y eso desordeno bastante la sesion."
    if dominant_issue == "work_over_target":
        if session_family in {"activation", "interval"} and severity == "low":
            return f"La activacion se fue un poco arriba de lo previsto{weekly_context_note}, pero sin señales claras de sobrecarga."
        if session_family == "interval":
            if severity == "moderate":
                return f"Los bloques fuertes se fueron arriba de lo previsto{weekly_context_note}, mas por intensidad que por desorden."
            if severity == "high":
                return f"Los bloques fuertes quedaron claramente por encima de lo previsto{weekly_context_note} y la carga termino siendo mayor a la buscada."
        if session_family in {"base", "long_run"}:
            return f"Para una sesion de base, la intensidad se fue mas arriba de lo que convenia{weekly_context_note}."
        return f"La sesion se corrio por encima de la intensidad prevista{weekly_context_note}."
    if dominant_issue == "work_under_target":
        if severity == "low":
            return f"El trabajo principal quedo apenas corto de intensidad{weekly_context_note}, sin arruinar del todo la lectura."
        return f"El trabajo principal quedo algo corto de intensidad{weekly_context_note}, asi que el estimulo no termino de asentarse del todo."
    if dominant_issue == "structure_low_confidence":
        if severity == "high":
            return f"La estructura real quedo demasiado mezclada como para leer la sesion con confianza{weekly_context_note}."
        return f"La estructura real quedo algo desordenada{weekly_context_note} y eso complica la lectura fina."
    if dominant_issue == "controlled_without_extra_fatigue":
        return f"La sesion quedo controlada{weekly_context_note} y, mas importante, no parece haber dejado un costo extra innecesario."

    if is_pre_race and fatigue is not None and fatigue < 65:
        return f"Para el momento del plan, la sesion deja una sensacion de afinacion bastante limpia{weekly_context_note}."
    if overall == "cumplida" and control is not None and control >= 75:
        if session_family == "interval":
            return f"La sesion salio ordenada en lo importante{weekly_context_note}: los bloques principales dejaron una lectura util."
        if session_family in {"base", "long_run", "tempo"}:
            return f"La sesion quedo bien orientada{weekly_context_note} y mantuvo el estimulo que buscaba el plan."
    if overall == "parcial":
        return f"La sesion deja cosas utiles{weekly_context_note}, aunque no todo quedo tan fino como pedia el objetivo."
    if overall == "desviada":
        return f"La sesion no termino de parecerse a lo previsto{weekly_context_note} y hay que leerla con algo mas de cuidado."

    if compliance is not None and execution is not None and compliance >= 70 and execution >= 70:
        return f"La sesion deja una lectura mas positiva que negativa{weekly_context_note}, con un par de matices concretos."
    return f"La sesion deja una lectura mixta{weekly_context_note}: hubo cosas solidas, pero no quedo del todo redonda."


def _quick_takeaway_strengths(
    *,
    session_family: str,
    heart_rate: Mapping[str, Any],
    cadence: Mapping[str, Any],
    control: float | None,
    flags: Mapping[str, Any],
    recent: Mapping[str, Any],
    is_pre_race: bool,
) -> list[str]:
    strengths: list[str] = []
    if is_pre_race and control is not None and control >= 75:
        strengths.append("que la activacion no se transformo en una carga pesada")
    elif control is not None and control >= 75:
        strengths.append("un control bastante prolijo de la intensidad")
    if heart_rate and not flags.get("cardiac_drift_flag"):
        strengths.append("la ausencia de deriva cardiaca")
    if cadence and cadence.get("stability_score") is not None and cadence["stability_score"] >= 75:
        strengths.append("una cadencia estable")
    if session_family == "interval" and not flags.get("interval_structure_low_confidence_flag"):
        strengths.append("una estructura reconocible entre trabajo y recuperaciones")
    if recent and recent.get("duration_vs_recent_avg_pct") is not None and abs(recent["duration_vs_recent_avg_pct"]) <= 10:
        strengths.append("una carga muy parecida a la de las sesiones recientes comparables")
    return strengths


def _quick_takeaway_caution(
    *,
    dominant_issue: str | None,
    session_family: str,
    severity: str,
    flags: Mapping[str, Any],
    block_analysis: list[dict[str, Any]],
    heart_rate: Mapping[str, Any],
    pace: Mapping[str, Any],
    fatigue: float | None,
    is_pre_race: bool,
) -> str | None:
    if dominant_issue == "recovery_not_effective":
        if severity == "low":
            return "Las pausas quedaron algo vivas, pero no aparecen señales claras de que eso haya disparado una sobrecarga real."
        if flags.get("recovery_block_too_fast_flag"):
            return "Las pausas quedaron demasiado vivas y eso hizo que la recuperacion no cumpliera del todo su funcion."
        return "Las recuperaciones no terminaron de bajar la intensidad como convenia, y eso cambia bastante la lectura del bloque."
    if dominant_issue == "work_over_target":
        block = _first_block_by_status(block_analysis, "above_range")
        if block:
            label = str(block.get("planned_label", "los bloques principales")).lower()
            if session_family == "interval":
                if severity == "low":
                    return f"El exceso estuvo sobre todo en {label}, aunque sin un costo fisiologico que hoy preocupe demasiado."
                return f"El exceso estuvo sobre todo en {label}, donde el ritmo se fue mas rapido de lo previsto."
            return f"El bloque principal se fue por encima del objetivo en {label}."
        if session_family in {"base", "long_run"}:
            return "El problema no fue la estructura, sino haber convertido una sesion que pedia control en algo mas intenso de la cuenta."
        return "El trabajo principal se fue algo por encima del objetivo."
    if dominant_issue == "work_under_target":
        if severity == "low":
            return "Falto un poco de precision en el objetivo, pero el estimulo general sigue siendo util."
        return "Los bloques principales quedaron algo por debajo del objetivo y eso le quita especificidad al estimulo."
    if dominant_issue == "structure_low_confidence":
        if severity == "moderate":
            return "La estructura real se mezclo lo suficiente como para que la lectura por bloques pierda bastante claridad."
        return "El problema no fue solo la intensidad: la estructura real quedo demasiado mezclada y eso baja la confianza de la lectura."
    if flags.get("heart_rate_high_flag") and not flags.get("heat_impact_flag"):
        if is_pre_race:
            return "La intensidad se fue un poco arriba para una sesion de afinacion, aunque sin señales de descontrol fuerte."
        return "La frecuencia cardiaca quedo un poco mas alta de lo esperable para esta lectura."
    if flags.get("pace_instability_flag") and pace.get("stability_cv") is not None:
        return "El ritmo tuvo mas variacion de la ideal para leer la sesion como totalmente limpia."
    if fatigue is not None and fatigue >= 78:
        return "El costo fisiologico fue alto y eso matiza bastante la lectura final."
    if heart_rate and heart_rate.get("cardiac_drift_ratio") is not None and heart_rate["cardiac_drift_ratio"] >= 0.05:
        return "Aparecen senales de desgaste progresivo, aunque no necesariamente invalidan la sesion."
    return None


def _quick_takeaway_learning(
    *,
    dominant_issue: str | None,
    session_family: str,
    severity: str,
    flags: Mapping[str, Any],
    block_analysis: list[dict[str, Any]],
    metrics: Mapping[str, Any],
    context: Any,
    is_pre_race: bool,
    days_to_goal: int | None,
) -> str | None:
    if dominant_issue == "recovery_not_effective":
        if severity == "low":
            return "La principal correccion es no regalar intensidad en las pausas, sobre todo si la idea era activar sin sumar fatiga."
        return "La principal correccion para la proxima es recuperar de verdad entre repeticiones, porque ahi estuvo el mayor desvio."
    if dominant_issue == "work_over_target":
        if is_pre_race:
            if severity == "low":
                return "Tan cerca de la carrera, es preferible quedar con sensacion de soltura antes que exprimir un poco mas cada bloque."
            return "Tan cerca de la carrera, conviene llegar con soltura y no convertir los bloques buenos en un esfuerzo de mas."
        if session_family in {"base", "long_run"}:
            return "La principal correccion es respetar mas el control del rodaje para que el volumen no se convierta en carga innecesaria."
        return "La principal correccion para la proxima es sostener el rango objetivo sin buscar un plus de intensidad que no aporta tanto."
    if dominant_issue == "work_under_target":
        return "La principal correccion para la proxima es entrar antes en el ritmo objetivo para que el bloque deje exactamente el estimulo buscado."
    if dominant_issue == "structure_low_confidence":
        return "La principal enseñanza es ordenar mejor la ejecucion para que cada bloque se pueda leer y comparar con mas claridad."

    session_intent = metrics.get("session_intent")
    if is_pre_race and days_to_goal is not None:
        return f"Con la carrera a {days_to_goal} dias, esta sesion sirve mas como recordatorio de sensaciones que como trabajo para sumar carga."
    if session_intent in {"interval_training", "mixed_structured"}:
        return "La lectura mas util es mirar cada bloque por su objetivo y no la sesion completa como si fuera un rodaje parejo."

    if _first_block_by_status(block_analysis, "within_range"):
        return "La principal enseñanza es repetir esta misma sensacion de control cuando toque una sesion parecida."

    sport = (context.planned_session.sport_type or "").lower()
    if sport == "running":
        return "Para la proxima, conviene mirar mas el objetivo del bloque que la sensacion general cuando la sesion pide precision."
    return "Para la proxima, conviene repetir esta lectura con un poco mas de precision en el objetivo central."


def _quick_takeaway_dominant_issue(
    flags: Mapping[str, Any],
    scores: Mapping[str, Any],
    block_analysis: list[dict[str, Any]],
) -> str | None:
    if flags.get("recovery_block_not_effective_flag"):
        return "recovery_not_effective"
    if flags.get("work_block_over_target_flag"):
        return "work_over_target"
    if flags.get("work_block_under_target_flag"):
        return "work_under_target"
    if flags.get("interval_structure_low_confidence_flag"):
        return "structure_low_confidence"
    fatigue = scores.get("fatigue_score")
    control = scores.get("control_score")
    if fatigue is not None and fatigue < 65 and control is not None and control >= 75:
        return "controlled_without_extra_fatigue"
    if _first_block_by_status(block_analysis, "above_range"):
        return "work_over_target"
    if _first_block_by_status(block_analysis, "below_range"):
        return "work_under_target"
    return None


def _quick_takeaway_session_family(session_intent: str | None, is_pre_race: bool) -> str:
    if is_pre_race:
        return "activation"
    if session_intent in {"interval_training", "mixed_structured"}:
        return "interval"
    if session_intent == "tempo":
        return "tempo"
    if session_intent == "long_endurance":
        return "long_run"
    if session_intent == "base_aerobic":
        return "base"
    return "general"


def _quick_takeaway_contextual_severity(
    *,
    dominant_issue: str | None,
    session_family: str,
    flags: Mapping[str, Any],
    scores: Mapping[str, Any],
    metrics: Mapping[str, Any],
    is_pre_race: bool,
) -> str:
    severity_points = 0
    fatigue = scores.get("fatigue_score")
    control = scores.get("control_score")
    heart_rate = metrics.get("heart_rate") or {}
    planned_vs_actual = metrics.get("planned_vs_actual") or {}

    if dominant_issue in {"work_over_target", "work_under_target", "recovery_not_effective"}:
        severity_points += 1
    if dominant_issue == "structure_low_confidence":
        severity_points += 2

    if flags.get("recovery_block_not_effective_flag"):
        severity_points += 1
    if flags.get("recovery_block_too_fast_flag"):
        severity_points += 1
    if flags.get("work_block_over_target_flag") or flags.get("work_block_under_target_flag"):
        severity_points += 1
    if flags.get("interval_structure_low_confidence_flag"):
        severity_points += 2
    if flags.get("cardiac_drift_flag"):
        severity_points += 2
    if flags.get("heart_rate_high_flag"):
        severity_points += 1

    avg_hr_pct = heart_rate.get("avg_hr_pct_of_max")
    if avg_hr_pct is not None:
        if avg_hr_pct >= 0.9:
            severity_points += 2
        elif avg_hr_pct >= 0.84:
            severity_points += 1

    drift_ratio = heart_rate.get("cardiac_drift_ratio")
    if drift_ratio is not None:
        if drift_ratio >= 0.08:
            severity_points += 2
        elif drift_ratio >= 0.05:
            severity_points += 1

    duration_delta_pct = (((planned_vs_actual.get("duration") or {}).get("delta_pct")))
    distance_delta_pct = (((planned_vs_actual.get("distance") or {}).get("delta_pct")))
    if duration_delta_pct is not None and abs(duration_delta_pct) >= 20:
        severity_points += 1
    if distance_delta_pct is not None and abs(distance_delta_pct) >= 20:
        severity_points += 1

    if fatigue is not None:
        if fatigue >= 82:
            severity_points += 2
        elif fatigue >= 72:
            severity_points += 1
        elif fatigue <= 62:
            severity_points -= 1

    if control is not None:
        if control >= 78:
            severity_points -= 1
        elif control < 60:
            severity_points += 1

    if session_family == "activation":
        severity_points -= 1
        if (
            dominant_issue in {"work_over_target", "recovery_not_effective"}
            and not flags.get("cardiac_drift_flag")
            and (fatigue is None or fatigue < 72)
            and (control is None or control >= 65)
            and (avg_hr_pct is None or avg_hr_pct < 0.88)
        ):
            severity_points -= 1
    elif session_family == "interval":
        severity_points += 0
    elif session_family in {"base", "long_run"} and dominant_issue == "work_over_target":
        severity_points += 1
    elif session_family == "tempo" and dominant_issue == "work_over_target":
        severity_points += 0

    if severity_points <= 1:
        return "low"
    if severity_points <= 4:
        return "moderate"
    return "high"


def _days_to_goal(context: Any) -> int | None:
    goal = getattr(context.planned_session, "goal", None)
    session_date = getattr(context.planned_session, "session_date", None)
    if goal is None or getattr(goal, "event_date", None) is None or session_date is None:
        return None
    return (goal.event_date - session_date).days


def _first_block_by_status(block_analysis: list[dict[str, Any]], target_status: str) -> dict[str, Any] | None:
    for block in block_analysis:
        target_eval = block.get("target_evaluation") or {}
        if target_eval.get("status") == target_status:
            return block
    return None


def _join_phrases(items: list[str]) -> str:
    clean = [item.strip() for item in items if item and item.strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} y {clean[1]}"
    return f"{', '.join(clean[:-1])} y {clean[-1]}"


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


def _is_low_hrv_status(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip().lower()
    if not normalized:
        return False
    low_markers = ("low", "unbalanced", "below", "poor", "reduced", "baja", "bajo", "desequilibr")
    return any(marker in normalized for marker in low_markers)


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
