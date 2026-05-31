# MCP Week Metrics JSON

## Weekly RAW Metrics Mode

`get_week_metrics_json` es la tool principal para analisis semanal conversacional.

El backend solo expone el `metrics_json` tecnico ya guardado en `WeeklyAnalysis`.
ChatGPT hace la interpretacion semanal.

## Tools

- `get_week_metrics_json(athlete_id, week_start_date?, week_end_date?, reference_date?)`
- `get_my_week_metrics_json(access_code, week_start_date?, week_end_date?, reference_date?)`

## Resolucion

1. Si viene `week_start_date`, usa esa semana.
2. Si viene `reference_date`, busca la semana que contiene esa fecha.
3. Si no viene nada, usa la ultima semana con `metrics_json` disponible.
4. Si hay ambiguedad real, devuelve error claro.
5. No recalcula nada.

## Payload

- `schema_version`
- `athlete`
- `week`
- `metrics_json_available`
- `metrics_json`
- `limitations`

`metrics_json` se devuelve completo, sin resumir y sin filtrar.

## Regla de uso

Para analisis semanal conversacional usar siempre `get_week_metrics_json`.

Las tools semanales narrativas o duplicadas quedan deprecated para MCP publico:

- `get_latest_weekly_analysis`
- `get_week_load_summary`
- `get_my_week_load_summary`

## Garantias

- Read-only
- No modifica DB
- No recalcula `metrics_json`
- No llama IA
- No sincroniza Garmin
