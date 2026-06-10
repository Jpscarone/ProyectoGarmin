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

### `POST /api/mcp/plan-import/verify`

Body:

```json
{
  "import_text": "WEEK\nATHLETE_ID: 1\n...\nEND"
}
```

Verifica en modo read-only que el bloque importable haya quedado reflejado en DB. No escribe nada.

Devuelve:

- `valid`
- `athlete`
- `week_start_date`
- `week_end_date`
- `expected_sessions`
- `matched_sessions`
- `missing_sessions`
- `different_sessions`
- `extra_sessions_same_week`
- `summary`
- `warnings`

Reglas:

- si hay `missing_sessions` o `different_sessions`, `valid=false`
- si solo hay `extra_sessions_same_week`, `valid=true` con warnings
- busca por `SESSION_ID` cuando existe; si no, por `DATE + SPORT` y trata de validar `NAME`
- compara `date`, `sport`, `name`, `modality`, `session_type`, duracion total y cantidad de bloques
- para `cancel`, verifica que la sesion exista y quede marcada como `cancelled`
- soporta bloques sin `WEEK`, pero si no puede resolver un atleta de forma segura devuelve error claro

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
SESSION_TYPE: required
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

`WEEK`, `START_DATE`, `END_DATE` y `MODE` son opcionales. `ATHLETE_ID` debe incluirse para uso MCP multiatleta; `ATHLETE_NAME` es opcional y se usa como control humano. Debe existir al menos un cierre explicito con `END`, `END_SESSION` o `END_WEEK`.

Marcadores soportados:

- `END`: compatible con el formato viejo. Puede cerrar `BLOCK`, `SESSION` o `WEEK` segun contexto.
- `END_BLOCK`: cierra un `BLOCK` de forma explicita.
- `END_SESSION`: cierra una `SESSION` de forma explicita.
- `END_WEEK`: cierra `WEEK` de forma explicita.

Formatos validos:

Formato compacto historico:

```text
SESSION
...
BLOCK
...
BLOCK
...
END
```

Formato explicito/intuitivo:

```text
SESSION
...
BLOCK
...
END
BLOCK
...
END
END
```

Formato sin ambiguedad recomendado:

```text
SESSION
...
BLOCK
...
END_BLOCK
BLOCK
...
END_BLOCK
END_SESSION
END_WEEK
```

Si `END` se interpreta solo como cierre de `BLOCK`, preview y verify devuelven el warning:

```text
Se interpreto END como cierre de BLOCK. Se recomienda usar END_BLOCK para evitar ambiguedad.
```

`SESSION_TYPE` soporta:

- `required`
- `optional`
- `recovery`
- `race`
- `test`

Si no viene `SESSION_TYPE`, la importacion usa `required` por compatibilidad. Si `NOTES` contiene `opcional` u `optional`, preview infiere `SESSION_TYPE: optional` y devuelve el warning:

```text
Se detecto opcional por notas; se recomienda usar SESSION_TYPE: optional.
```

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

## Reglas de modelado

- `WEEK` debe incluir `ATHLETE_ID` y `ATHLETE_NAME`.
- No importar dias de descanso como `SESSION`.
- No usar `SPORT: recovery`.
- Si queres registrar movilidad real: `SPORT: mobility` y `SESSION_TYPE: recovery`.
- Bici opcional: `SESSION_TYPE: optional`.
- Gym opcional: `SESSION_TYPE: optional`.
- Sesion clave y fondo: `SESSION_TYPE: required`.
- Carrera objetivo: `SESSION_TYPE: race`.
- Test controlado: `SESSION_TYPE: test`.

## Prompt Maestro Para El Chat De Planificacion Semanal

Usar este prompt base cuando quieras que el chat proponga un bloque importable limpio:

```text
Genera un bloque importable V2 para ProyectoGarmin.

Reglas obligatorias:
- Incluir WEEK, ATHLETE_ID, ATHLETE_NAME, START_DATE, END_DATE y MODE: preview.
- No importar dias de descanso como SESSION.
- Toda SESSION debe incluir ACTION, DATE, SPORT, SESSION_TYPE y NAME.
- No usar SPORT: recovery.
- Si hay movilidad/activacion real, usar SPORT: mobility y SESSION_TYPE: recovery.
- Bici o gym opcional deben usar SESSION_TYPE: optional.
- Fondo y sesiones clave deben usar SESSION_TYPE: required.
- Carrera objetivo debe usar SESSION_TYPE: race.
- Test controlado debe usar SESSION_TYPE: test.
- Si una sesion tiene bloques, agregarlos con BLOCK.
- No aplicar cambios; solo devolver el import_text.
```

Ejemplo:

```text
WEEK
ATHLETE_ID: 1
ATHLETE_NAME: Pablo
START_DATE: 2026-05-25
END_DATE: 2026-05-31
MODE: preview

SESSION
ACTION: upsert
DATE: 2026-05-27
SPORT: cycling
SESSION_TYPE: optional
MODALITY: outdoor
NAME: Bici suave pre fondo
NOTES: activacion aerobica sin cargar piernas

BLOCK
VALUE: 45
UNIT: min
INTENSITY: rpe
RPE_MIN: 2
RPE_MAX: 4

SESSION
ACTION: upsert
DATE: 2026-05-31
SPORT: running
SESSION_TYPE: required
NAME: Fondo progresivo

BLOCK
VALUE: 100
UNIT: min

END
```
