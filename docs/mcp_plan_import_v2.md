# MCP Plan Import V2

## Objetivo

V2 agrega escritura controlada para importar planificacion desde texto estructurado. Permite previsualizar sin escribir y aplicar altas, modificaciones, upserts, cancelaciones y cargas masivas de sesiones.

No borra sesiones fisicamente, no dispara sincronizacion Garmin y no ejecuta analisis IA.

## Seguridad

- `POST /api/mcp/plan-import/preview` acepta `MCP_API_TOKEN` o `MCP_WRITE_API_TOKEN`.
- `POST /api/mcp/plan-import/commit` exige `MCP_WRITE_API_TOKEN`.
- `commit` tambien exige `"confirmation": "APLICAR"`.

Header:

```http
Authorization: Bearer TU_TOKEN
```

## Endpoints

### `POST /api/mcp/plan-import/preview`

Body:

```json
{
  "import_text": "WEEK\nATHLETE_ID: 1\nATHLETE_NAME: Pablo\n\nSESSION\nACTION: create\nDATE: 2026-05-26\nSPORT: running\nNAME: Rodaje suave\n\nBLOCK\nVALUE: 30\nUNIT: min\n\nEND"
}
```

Devuelve `valid`, operaciones por sesion y errores. No escribe en DB.

Operaciones posibles: `will_create`, `will_update`, `will_cancel`, `conflict`, `not_found`, `invalid`.

### `POST /api/mcp/plan-import/commit`

Body:

```json
{
  "import_text": "...",
  "confirmation": "APLICAR"
}
```

Aplica todo el bloque en una transaccion. Si una operacion falla, hace rollback completo.

Respuesta: `created`, `updated`, `cancelled`, `skipped`, `errors`, `affected_session_ids`.

## Formato

```text
WEEK
ATHLETE_ID: 1
ATHLETE_NAME: Pablo
START_DATE: 2026-05-25
END_DATE: 2026-05-31
MODE: preview

SESSION
ACTION: upsert
DATE: 2026-05-26
SPORT: strength
MODALITY: indoor
NAME: Gimnasio suave
NOTES: mantenimiento y movilidad sin fatigar piernas

BLOCK
VALUE: 45
UNIT: min
INTENSITY: rpe
ZONE: custom
RPE_MIN: 3
RPE_MAX: 5

SESSION
ACTION: cancel
DATE: 2026-05-27
SPORT: running
REASON: fatiga alta

END
```

`WEEK`, `START_DATE`, `END_DATE` y `MODE` son opcionales. `ATHLETE_ID` debe incluirse para uso MCP multiatleta; `ATHLETE_NAME` es opcional y se usa como control humano. `END` es obligatorio.

Si `ATHLETE_NAME` no coincide con el nombre real del `ATHLETE_ID`, preview devuelve el warning:

```text
ATHLETE_NAME no coincide con el atleta encontrado para ATHLETE_ID.
```

## Semantica

- `create`: crea si no existe una sesion misma fecha + sport.
- `update`: actualiza por `SESSION_ID`; si no viene, busca por `DATE + SPORT`.
- `upsert`: actualiza y reemplaza bloques si existe `DATE + SPORT`; si no existe, crea.
- `cancel`: marca `completion_source="cancelled"` y guarda `REASON` en notas disponibles.

Si hay mas de una coincidencia por `DATE + SPORT`, preview devuelve `conflict` y commit no aplica.

`ATHLETE_ID` dentro del bloque tiene prioridad sobre cualquier `athlete_id` enviado en el body.
