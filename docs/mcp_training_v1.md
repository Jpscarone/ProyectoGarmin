# MCP Training V1

## Objetivo

Esta V1 expone contexto de entrenamiento de la app mediante endpoints HTTP pensados para clientes MCP.
La integracion es solo lectura: no crea, edita ni borra sesiones, no dispara sincronizacion con Garmin y no ejecuta analisis IA nuevos.

## Seguridad

Todos los endpoints requieren Bearer token.

Variable de entorno requerida:

- `MCP_API_TOKEN`

Header esperado:

```http
Authorization: Bearer TU_TOKEN
```

Si `MCP_API_TOKEN` no esta configurado, la API responde `500`.
Si el header `Authorization` no coincide, responde `401`.

## Endpoints

### `GET /api/mcp/session-feedback?date=YYYY-MM-DD`

Devuelve contexto de una fecha puntual:

- atleta
- objetivo actual
- sesion planificada
- actividad realizada compatible o vinculada
- analisis disponible
- resumen de semana
- proxima sesion
- decision sugerida

### `GET /api/mcp/week-context`

Devuelve contexto resumido de la semana actual:

- sesiones planificadas
- actividades completadas
- carga semanal
- distribucion de intensidad si existe
- readiness resumido si existe
- warning principal
- recomendacion

### `GET /api/mcp/last-activity-feedback`

Devuelve la ultima actividad disponible, su sesion vinculada si existe, su analisis si existe y una recomendacion corta.

### `GET /api/mcp/next-session-context`

Devuelve contexto para decidir la proxima sesion:

- readiness de hoy si existe
- carga reciente
- proxima sesion
- objetivo actual
- recomendacion

## Ejemplos de uso

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" \
  "http://localhost:8000/api/mcp/session-feedback?date=2026-05-01"
```

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" \
  "http://localhost:8000/api/mcp/week-context"
```

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" \
  "http://localhost:8000/api/mcp/last-activity-feedback"
```

```bash
curl -H "Authorization: Bearer $MCP_API_TOKEN" \
  "http://localhost:8000/api/mcp/next-session-context"
```

## Alcance de V1

- Solo lectura
- Reutiliza datos ya guardados en la app
- Tolerante a faltantes: campos como actividad, analisis o readiness pueden volver `null`
