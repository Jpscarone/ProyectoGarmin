# ProyectoGarmin MCP Server

## Que hace

Este servidor MCP remoto consume la API interna read-only de ProyectoGarmin bajo `/api/mcp` y expone tools para consultar atletas, actividades, salud, estado de entrenamiento y comparaciones entre sesion programada y actividad realizada.

No se conecta directo a PostgreSQL.
No escribe datos.
No modifica el estado del sistema.

## Tools expuestas

- `get_athletes()`
- `get_recent_activities(athlete_id: int, limit: int = 10)`
- `get_activity_detail(athlete_id: int, activity_id: int)`
- `get_health_summary(athlete_id: int)`
- `get_latest_weekly_analysis(athlete_id: int)`
- `get_training_status(athlete_id: int)`
- `identify_me(access_code: str)`
- `get_my_recent_activities(access_code: str, limit: int = 10)`
- `get_my_health_summary(access_code: str)`
- `get_my_training_status(access_code: str)`
- `compare_planned_vs_done(athlete_id: int, date: str | None = None, activity_id: int | None = None, planned_session_id: int | None = None)`
- `compare_my_planned_vs_done(access_code: str, date: str | None = None)`
- `get_next_session_recommendation(athlete_id: int, reference_date: str | None = None, planned_session_id: int | None = None)`
- `get_my_next_session_recommendation(access_code: str, reference_date: str | None = None)`
- `get_week_load_summary(athlete_id: int, week_start_date: str | None = None, compare_previous: bool = True)`
- `get_my_week_load_summary(access_code: str, week_start_date: str | None = None, compare_previous: bool = True)`
- `get_session_analysis_payload(athlete_id: int, planned_session_id: int | None = None, activity_id: int | None = None, date: str | None = None)`
- `get_my_session_analysis_payload(access_code: str, date: str | None = None, activity_id: int | None = None, planned_session_id: int | None = None)`

## Acceso experimental por atleta

Ademas de las tools admin/coach basadas en `athlete_id`, existe una capa experimental orientada al atleta con `access_code`.

- El atleta no necesita conocer `athlete_id`.
- Las tools `my_*` solo aceptan `access_code`.
- La API resuelve internamente el atleta y nunca permite consultar otro `athlete_id`.
- Todo sigue siendo read-only.

Creacion de codigo:

```powershell
python .\scripts\create_athlete_access_code.py --athlete-id 2 --label "Carolina ChatGPT" --prefix CARO
```

Ejemplo de salida:

```text
Athlete access code created: id=7 athlete_id=2 athlete_name=Carolina access_code=CARO-7K92-XP31
```

Codigo manual:

```powershell
python .\scripts\create_athlete_access_code.py --athlete-id 2 --code CARO-TEST-1234 --label "Carolina ChatGPT"
```

Revocacion o desactivacion:

- Esta V1 no tiene pantalla web todavia.
- Ahora existe pantalla web para admin/coach en `/admin/mcp-access-codes`.
- Tambien se puede desactivar manualmente `athlete_access_codes.is_active = false` en base si hace falta soporte rapido.

Advertencias de seguridad:

- Esta V1 guarda `access_code` en texto plano por simplicidad experimental.
- Sirve solo para atletas conocidos y escenarios controlados.
- No usar este enfoque con usuarios externos o desconocidos.
- Una iteracion futura puede migrar a hash, rotacion o OAuth.

## Nueva tool comparativa

`compare_planned_vs_done` consulta `GET /api/mcp/compare/planned-vs-done` y devuelve un JSON read-only con:

- atleta y fecha resuelta
- sesion programada normalizada
- actividad realizada normalizada
- metadata de match: `explicit`, `date_sport` o `none`
- analisis comparativo existente si ya fue generado
- diferencias simples de duracion y distancia

La tool esta pensada para prompts como:

- `Comparame la ultima actividad de Pablo con lo que tenia programado`
- `Que tan bien cumplio la sesion del 2026-05-13`
- `Dame feedback entre programado y realizado`

## Nueva tool de recomendacion

`get_next_session_recommendation` consulta `GET /api/mcp/training/next-session-recommendation` y devuelve un JSON read-only con:

- atleta, fecha de referencia y plan activo o mas relevante
- proxima sesion objetivo
- ultima actividad realizada
- ultimo contexto de salud/readiness disponible
- ultimo contexto semanal disponible
- recomendacion operativa: `keep`, `reduce`, `replace_easy`, `rest`, `caution` o `no_data`

La tool esta pensada para prompts como:

- `Mantengo la sesion de manana o la ajusto`
- `Estoy para hacer calidad hoy`
- `Dame una recomendacion para la proxima sesion`

## Nueva tool de carga semanal

`get_week_load_summary` consulta `GET /api/mcp/training/week-load-summary` y devuelve un JSON read-only con:

- resumen de la semana actual o indicada
- actividades realizadas y sesiones planificadas
- carga total, distancia, duracion e intensidad
- promedio semanal de salud/readiness cuando haya datos
- weekly_analysis si existe
- comparacion con la semana previa

La tool esta pensada para prompts como:

- `Como viene mi semana de carga`
- `Comparame esta semana con la anterior`
- `Estoy acumulando demasiada intensidad`
- `Dame un resumen de carga semanal del atleta 1`

## Nueva tool de payload tecnico

`get_session_analysis_payload` consulta `GET /api/mcp/analysis/session-payload` y devuelve un JSON read-only con:

- sesion programada y pasos planificados
- actividad realizada y laps
- tabla step-vs-lap
- `metrics_json` y `llm_json` del analisis guardado
- warnings de calidad cuando falte vinculacion o analisis

La tool esta pensada para prompts como:

- `Traeme el payload de analisis de la ultima actividad de Pablo`
- `Dame feedback tecnico por bloques usando el payload de sesion`
- `Mostrame laps, steps y metrics_json de la sesion del 2026-05-15`

## Dependencias

Este servidor usa:

- `mcp`
- `httpx`
- `python-dotenv`

## Variables de entorno

Copiá `.env.example` a `.env`:

```powershell
Copy-Item .\mcp_training_server\.env.example .\mcp_training_server\.env
notepad .\mcp_training_server\.env
```

Ejemplo:

```env
TRAINING_APP_BASE_URL=http://127.0.0.1:8000
TRAINING_APP_MCP_TOKEN=change-me

MCP_TRANSPORT=http
MCP_HOST=127.0.0.1
MCP_PORT=9000
MCP_HTTP_PATH=/mcp
MCP_SSE_PATH=/sse
MCP_MESSAGE_PATH=/messages/
```

Variables:

- `TRAINING_APP_BASE_URL`: URL base de la app principal.
- `TRAINING_APP_MCP_TOKEN`: token bearer que la app principal exige para `/api/mcp/*`.
- `MCP_TRANSPORT`: `stdio`, `http` o `sse`.
- `MCP_HOST`: host del servidor MCP remoto.
- `MCP_PORT`: puerto del servidor MCP remoto.
- `MCP_HTTP_PATH`: path para streamable HTTP.
- `MCP_SSE_PATH`: path para SSE.
- `MCP_MESSAGE_PATH`: path auxiliar para mensajes SSE.

## Instalacion local

```powershell
python -m venv .\mcp_training_server\.venv
.\mcp_training_server\.venv\Scripts\Activate.ps1
python -m pip install -r .\mcp_training_server\requirements.txt
```

## Como correr localmente

### Modo stdio

```powershell
$env:TRAINING_APP_BASE_URL = "http://127.0.0.1:8000"
$env:TRAINING_APP_MCP_TOKEN = "change-me"
$env:MCP_TRANSPORT = "stdio"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\server.py
```

### Modo remoto HTTP

```powershell
$env:TRAINING_APP_BASE_URL = "http://127.0.0.1:8000"
$env:TRAINING_APP_MCP_TOKEN = "change-me"
$env:MCP_TRANSPORT = "http"
$env:MCP_HOST = "0.0.0.0"
$env:MCP_PORT = "9000"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\server.py
```

URL MCP esperada:

```text
http://127.0.0.1:9000/mcp
```

### Modo remoto SSE

```powershell
$env:TRAINING_APP_BASE_URL = "http://127.0.0.1:8000"
$env:TRAINING_APP_MCP_TOKEN = "change-me"
$env:MCP_TRANSPORT = "sse"
$env:MCP_HOST = "0.0.0.0"
$env:MCP_PORT = "9000"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\server.py
```

## Como probar

### Smoke test de la API interna

```powershell
$env:TRAINING_APP_BASE_URL = "http://127.0.0.1:8000"
$env:TRAINING_APP_MCP_TOKEN = "change-me"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\smoke_test_api.py
```

### Probar solo la comparacion interna

```powershell
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/compare/planned-vs-done?athlete_id=1"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/compare/planned-vs-done?athlete_id=1&date=2026-05-13"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/compare/planned-vs-done?athlete_id=1&activity_id=123"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/compare/planned-vs-done?athlete_id=1&planned_session_id=456"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/next-session-recommendation?athlete_id=1"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/next-session-recommendation?athlete_id=1&reference_date=2026-05-13"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/next-session-recommendation?athlete_id=1&planned_session_id=456"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/week-load-summary?athlete_id=1"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/week-load-summary?athlete_id=1&week_start_date=2026-05-11"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/week-load-summary?athlete_id=1&week_start_date=2026-05-11&compare_previous=false"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/analysis/session-payload?athlete_id=1"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/analysis/session-payload?athlete_id=1&planned_session_id=456"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/analysis/session-payload?athlete_id=1&activity_id=123"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/analysis/session-payload?athlete_id=1&date=2026-05-15"
```

### Smoke test remoto MCP

Primero levantá el server MCP remoto y luego, en otra consola:

```powershell
$env:MCP_REMOTE_URL = "http://127.0.0.1:9000/mcp"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\smoke_test_remote.py
```

## Como correr en VPS

1. Configurá `.env` con la URL interna real de la app principal.
2. Elegí `MCP_TRANSPORT=http`.
3. Levantá el proceso con `systemd`, `supervisor` o el process manager que uses.
4. Publicá el puerto detrás de Nginx o Caddy con HTTPS.

Ejemplo de variables:

```env
TRAINING_APP_BASE_URL=http://127.0.0.1:8000
TRAINING_APP_MCP_TOKEN=super-secret
MCP_TRANSPORT=http
MCP_HOST=127.0.0.1
MCP_PORT=9000
MCP_HTTP_PATH=/mcp
```

## Errores manejados

- `401`: token inválido o faltante en la API interna.
- `404`: atleta o actividad inexistente.
- `503`: API interna MCP no disponible o token MCP de la app no configurado.
- `500+`: error interno de la app principal.

Las tools devuelven errores cortos y legibles, sin stacktrace largo.

## Proximos pasos para exponerlo por HTTPS

1. Levantar el MCP en modo `http`.
2. Publicarlo detrás de Nginx o Caddy.
3. Asegurar una URL HTTPS pública.
4. Apuntar ChatGPT / MCP Inspector a:

```text
https://tu-dominio.com/mcp
```
