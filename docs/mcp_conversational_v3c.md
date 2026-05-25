# MCP Conversational V3C

## Objetivo

V3C agrega herramientas read-only de decision y ajuste de plan.

No modifica la base.
No llama `commit_plan_import`.
No aplica cambios.
Solo devuelve:

- sugerencias
- decisiones
- impacto probable
- contexto
- texto importable V2 para preview posterior

## Endpoints

### `GET /api/mcp/plan-adjustment-suggestions`

Params:

- `athlete_id`
- `reference_date` opcional

Wrapper:

- `GET /api/mcp/me/plan-adjustment-suggestions?access_code=...`

Preguntas:

- `Tengo que modificar algo esta semana?`
- `Tocarias algo de esta semana?`

### `GET /api/mcp/next-session-decision`

Params:

- `athlete_id`
- `reference_date` opcional
- `planned_session_id` opcional

Wrapper:

- `GET /api/mcp/me/next-session-decision?access_code=...`

Preguntas:

- `Mantengo el entrenamiento de manana?`
- `Que hago con la proxima sesion?`
- `Estoy para hacer intensidad?`

### `GET /api/mcp/optional-session-impact`

Params:

- `athlete_id`
- `planned_session_id` opcional
- `date` opcional
- `sport` opcional

Wrapper:

- `GET /api/mcp/me/optional-session-impact?access_code=...`

Preguntas:

- `Puedo saltear la bici?`
- `Que pasa si no hago la bici?`
- `Que pasa si cancelo esta sesion opcional?`

### `GET /api/mcp/generate-plan-adjustment-import-text`

Params:

- `athlete_id`
- `adjustment_type`
- `reference_date` opcional
- `planned_session_id` opcional
- `reason` opcional

Wrapper:

- `GET /api/mcp/me/generate-plan-adjustment-import-text?access_code=...`

Preguntas:

- `Generame el importable para cancelar la bici opcional.`
- `Armame el importable para bajar la sesion de manana.`
- `Proponeme el ajuste en formato importable.`

Notas:

- el resultado no se aplica
- siempre exige preview posterior
- si no puede armar algo seguro devuelve `generated=false`

### `GET /api/mcp/training-decision-context`

Params:

- `athlete_id`
- `reference_date` opcional

Wrapper:

- `GET /api/mcp/me/training-decision-context?access_code=...`

Preguntas:

- `Dame contexto para decidir.`
- `Que deberia mirar antes de tocar el plan?`

## Ejemplos

### Tengo que modificar algo esta semana?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/plan-adjustment-suggestions?athlete_id=2&reference_date=2026-05-25"
```

### Mantengo el entrenamiento de manana?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/next-session-decision?athlete_id=2&reference_date=2026-05-25"
```

### Puedo saltear la bici?

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/optional-session-impact?athlete_id=2&date=2026-05-27&sport=cycling"
```

### Generame el importable para cancelar la bici opcional

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/generate-plan-adjustment-import-text?athlete_id=2&adjustment_type=cancel_optional&reason=fatiga"
```

### Dame contexto antes de tocar el plan

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" ^
  "http://localhost:8000/api/mcp/training-decision-context?athlete_id=2&reference_date=2026-05-25"
```
