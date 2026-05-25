# MCP Conversational V3B

## Objetivo

V3B agrega herramientas read-only para comparar semanas, leer tendencia de carga, resumir riesgo de fatiga, explicar la estrategia de una semana y componer un dashboard general desde datos reales.

No usa IA generativa.
No modifica sesiones.
No importa planes.
No rompe V1, V2 ni V3A.

## Endpoints

### `GET /api/mcp/week-comparison`

Params:

- `athlete_id`
- `week_start_date` opcional

Wrapper:

- `GET /api/mcp/me/week-comparison?access_code=...`

Preguntas:

- `Como fue esta semana contra la anterior?`
- `Hice mas o menos que la semana pasada?`

### `GET /api/mcp/training-load-trend`

Params:

- `athlete_id`
- `weeks` opcional, default `4`

Wrapper:

- `GET /api/mcp/me/training-load-trend?access_code=...`

Preguntas:

- `Estoy subiendo la carga?`
- `Vengo acumulando mucho?`
- `Como viene la carga de las ultimas semanas?`

Notas:

- usa duracion como proxy si no hay training load Garmin util
- no duplica sesiones manuales que ya tengan Garmin matcheado

### `GET /api/mcp/fatigue-risk-summary`

Params:

- `athlete_id`
- `reference_date` opcional

Wrapper:

- `GET /api/mcp/me/fatigue-risk-summary?access_code=...`

Preguntas:

- `Estoy acumulando fatiga?`
- `Conviene bajar algo?`
- `Estoy para meter intensidad?`

Notas:

- si hay salud, combina readiness local y carga reciente
- si no hay salud suficiente, puede devolver `unknown`

### `GET /api/mcp/week-strategy-summary`

Params:

- `athlete_id`
- `week_start_date` opcional

Wrapper:

- `GET /api/mcp/me/week-strategy-summary?access_code=...`

Preguntas:

- `Explicame esta semana.`
- `Que busca esta semana?`
- `Cual es la logica del plan?`

Notas:

- `strategy_label` se infiere por reglas simples y deterministicas
- usa nombres, notas, volumen estimado, sesiones clave, opcionales y objetivos en agenda

### `GET /api/mcp/training-dashboard`

Params:

- `athlete_id`
- `reference_date` opcional

Wrapper:

- `GET /api/mcp/me/training-dashboard?access_code=...`

Preguntas:

- `Como estoy hoy?`
- `Dame panorama general.`
- `Que deberia mirar antes del proximo entreno?`

Composicion:

- readiness
- adherence semanal
- remaining week plan
- next planned session
- last activity
- fatigue risk

## Ejemplos

### Como fue esta semana contra la anterior?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/week-comparison?athlete_id=2&week_start_date=2026-05-25"
```

### Estoy subiendo la carga?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/training-load-trend?athlete_id=2&weeks=4"
```

### Estoy acumulando fatiga?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/fatigue-risk-summary?athlete_id=2&reference_date=2026-05-25"
```

### Explicame esta semana

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/week-strategy-summary?athlete_id=2&week_start_date=2026-05-25"
```

### Como estoy hoy?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/training-dashboard?athlete_id=2&reference_date=2026-05-25"
```
