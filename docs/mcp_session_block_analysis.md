# MCP Session Block Analysis

## Objetivo

Exponer un payload tecnico read-only para analizar una sesion por bloques contra los laps reales de Garmin, sin disparar IA ni modificar vinculos o sesiones.

Sirve para preguntas como:

- `Analiza la sesion del 29/05/26 por bloques.`
- `Cumpli cada bloque?`
- `En que bloque me pase de pulsaciones?`
- `El bloque principal salio bien?`
- `Las recuperaciones fueron suficientes?`

## Endpoint

`GET /api/mcp/session-block-analysis-payload`

Query params:

- `athlete_id` obligatorio
- `planned_session_id` opcional
- `activity_id` opcional
- `date` opcional

Wrapper por clave:

- `GET /api/mcp/my/session-block-analysis-payload`
- `access_code` obligatorio

## Resolucion

1. Si viene `planned_session_id`, usa esa sesion.
2. Si viene `activity_id`, usa esa actividad y busca sesion vinculada.
3. Si viene `date`, intenta resolver sesion y actividad de ese dia.
4. Si la fecha es ambigua, devuelve `409` con candidatos.
5. No inventa matches nuevos.

## Payload

El resultado incluye:

- `planned_session` con bloques normalizados
- `activity` resumida
- `activity_laps`
- `raw_metrics_available`
- `block_matching`
- `overall_block_summary`
- `limitations`

`block_matching` compara por bloque:

- duracion planificada vs real
- FC objetivo vs FC media real por lap o grupo de laps
- comentario de ritmo si existiera target de pace
- `block_result`: `ok | slightly_high | too_high | too_low | incomplete | unknown`

## Reglas

- Si hay laps reales, se usan como fuente principal.
- Si `metrics_json.metrics.laps.pairs` existe, se prioriza para el matching.
- Si hay mas laps que bloques, agrupa por acumulacion de duracion.
- Si hay menos laps que bloques, marca matching parcial.
- Si no hay laps, devuelve `limitations` claras.
- Todo es read-only.
