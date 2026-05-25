# MCP Conversational V3

## Objetivo

V3 agrega endpoints y tools MCP read-only para responder preguntas naturales sobre planificacion, adherencia y contexto semanal sin obligar al usuario a navegar la UI.

No usa IA generativa.
Todo el resultado es deterministico y se deriva de:

- `planned_sessions`
- `training_days`
- matches con `garmin_activity`
- sesiones manuales de fuerza/gimnasio
- estados `cancelled` y `skipped`

V1 y V2 siguen intactas.

Desde la formalizacion de `SESSION_TYPE`, V3 distingue:

- `required`, `race` y `test`: cuentan para adherencia.
- `optional`: no penaliza adherencia si no se completa.
- `recovery`: no penaliza adherencia y queda separado de la carga principal salvo que se complete.

## Endpoints

### `GET /api/mcp/training/remaining-week-plan`

Params:

- `athlete_id`
- `week_start_date` opcional

Wrapper:

- `GET /api/mcp/me/training/remaining-week-plan?access_code=...`

Uso:

- `Que me queda esta semana?`

Respuesta:

- `week_start_date`
- `today`
- `completed_sessions`
- `remaining_sessions`
- `required_sessions`
- `optional_sessions`
- `recovery_sessions`
- `remaining_volume_minutes`
- `total_remaining_minutes_required`
- `total_remaining_minutes_optional`
- `sessions`

Notas:

- excluye canceladas y skipped
- usa `SESSION_TYPE` formal y mantiene fallback por texto solo para compatibilidad
- si no queda nada devuelve `message`

### `GET /api/mcp/training/previous-week-summary`

Params:

- `athlete_id`

Wrapper:

- `GET /api/mcp/me/training/previous-week-summary?access_code=...`

Uso:

- `Que hice la semana pasada?`

Respuesta:

- `week_start_date`
- `running_sessions`
- `strength_sessions`
- `cycling_sessions`
- `total_sessions`
- `total_duration_minutes`
- `adherence_percent`
- `completed_vs_planned`
- `highlights`

Notas:

- usa actividades Garmin y sesiones manuales
- no duplica fuerza manual si ya existe actividad Garmin vinculada

### `GET /api/mcp/training/next-planned-session`

Params:

- `athlete_id`
- `reference_date` opcional

Wrapper:

- `GET /api/mcp/me/training/next-planned-session?access_code=...`

Uso:

- `Que tengo manana?`
- `Que me toca despues?`

Respuesta:

- `date`
- `sport`
- `name`
- `duration_minutes`
- `notes`
- `blocks`

Notas:

- ignora canceladas, skipped y completadas
- si no encuentra nada devuelve `message`

### `GET /api/mcp/training/today-remaining-sessions`

Params:

- `athlete_id`

Wrapper:

- `GET /api/mcp/me/training/today-remaining-sessions?access_code=...`

Uso:

- `Me queda algo hoy?`

Respuesta:

- `date`
- `remaining_count`
- `sessions`

Notas:

- usa la fecha actual del server
- solo devuelve pendientes

### `GET /api/mcp/training/week-adherence`

Params:

- `athlete_id`
- `week_start_date` opcional

Wrapper:

- `GET /api/mcp/me/training/week-adherence?access_code=...`

Uso:

- `Cumpli la semana?`

Respuesta:

- `planned_sessions`
- `required_sessions`
- `optional_sessions`
- `recovery_sessions`
- `completed_sessions`
- `cancelled_sessions`
- `missed_sessions`
- `adherence_percent`
- `summary`

Formula:

- `adherence_percent = completed_sessions / required_sessions`

`required_sessions` incluye `required`, `race` y `test`.

`missed_sessions` cuenta solo sesiones exigibles no canceladas ni completadas ya vencidas a la fecha de consulta.

## Ejemplos

### Que me queda esta semana?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/training/remaining-week-plan?athlete_id=2&week_start_date=2026-05-25"
```

### Que hice la semana pasada?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/training/previous-week-summary?athlete_id=2"
```

### Que tengo manana?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/training/next-planned-session?athlete_id=2&reference_date=2026-05-25"
```

### Cumpli la semana?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/training/week-adherence?athlete_id=2&week_start_date=2026-05-18"
```
