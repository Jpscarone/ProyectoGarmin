# MCP Session Metrics JSON

## Objetivo

`get_session_metrics_json` es la tool principal para analisis conversacional de sesiones.

Devuelve el `metrics_json` ya guardado en `SessionAnalysis`, sin recalcular nada y sin disparar IA.

## Tools

- `get_session_metrics_json(athlete_id, planned_session_id?, activity_id?, date?)`
- `get_my_session_metrics_json(access_code, planned_session_id?, activity_id?, date?)`

En el MCP publico solo se mantiene el wrapper `get_my_session_metrics_json` para sesiones.

## Payload

La respuesta incluye:

- `planned_session`
- `activity`
- `metrics_json`
- `limitations`

`metrics_json` puede contener, segun disponibilidad:

- `block_analysis`
- `laps`
- `structured_match`
- `scores`
- `heart_rate`
- `pace`
- `planned_vs_actual`

## Regla de uso

Para analisis conversacional de sesiones usar siempre `get_session_metrics_json`.

Las tools MCP antiguas `get_activity_detail`, `compare_planned_vs_done` y `get_session_analysis_payload` quedan deprecated para el catalogo publico del MCP.

## Garantias

- Read-only
- No modifica DB
- No recalcula `metrics_json`
- No dispara analisis IA
- No sincroniza Garmin
