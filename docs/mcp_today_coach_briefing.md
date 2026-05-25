# MCP Today Coach Briefing

## Objetivo

`today_coach_briefing` compone un briefing diario read-only para responder:

- `Como estoy hoy?`
- `Dame el briefing del dia.`
- `Que tengo que hacer hoy?`
- `Me conviene entrenar?`
- `Que deberia mirar antes de entrenar?`

No usa IA generativa.
No modifica planificacion.
No dispara sync Garmin ni analisis.

## Endpoints

### `GET /api/mcp/today-coach-briefing`

Params:

- `athlete_id`
- `reference_date` opcional

### Wrappers por `access_code`

- `GET /api/mcp/me/today-coach-briefing?access_code=...`
- `GET /api/mcp/my/today-coach-briefing?access_code=...`

## Payload

Devuelve:

- `athlete`
- `date`
- `readiness`
- `today_sessions.completed`
- `today_sessions.remaining_required`
- `today_sessions.remaining_optional`
- `today_sessions.recovery`
- `next_session`
- `fatigue_risk`
- `week_context`
- `decision`
- `suggested_questions`

## Reglas

- `required`, `race` y `test` van a `remaining_required`
- `optional` va a `remaining_optional`
- `recovery` va a `recovery`
- completadas van a `completed`
- canceladas no aparecen como pendientes
- si no hay readiness, igual devuelve planificacion y decision con menor confianza
- si no hay sesiones hoy, igual devuelve la proxima sesion pendiente

## Decision diaria

- `green`: contexto estable, sin alertas fuertes y con posibilidad de sostener el plan
- `yellow`: se puede entrenar, pero conviene controlar carga o intensidad
- `red`: hay alertas fuertes y conviene bajar o modificar
- `unknown`: faltan datos clave, aunque la planificacion se muestra igual

## Ejemplos

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/today-coach-briefing?athlete_id=2&reference_date=2026-05-25"
```

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/my/today-coach-briefing?access_code=ATLETA-MCP-1234&reference_date=2026-05-25"
```
