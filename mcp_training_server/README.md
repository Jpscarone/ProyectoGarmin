# ProyectoGarmin MCP Server

## Que hace

Este servidor MCP remoto consume la API interna read-only de ProyectoGarmin bajo `/api/mcp` y expone tools para consultar atletas, actividades, salud, estado de entrenamiento y metrics tecnicos para analisis conversacional.

No se conecta directo a PostgreSQL.
Solo escribe datos mediante las tools V2 de importacion de planificacion, protegidas con token de escritura.

## Tools publicas oficiales

Basicas:

- `get_athletes()`
- `get_recent_activities(athlete_id: int, limit: int = 10)`
- `get_health_summary(athlete_id: int)`

Plan:

- `get_week_plan(athlete_id: int, week_start_date: str | None = None, include_completed: bool = True)`
- `get_day_plan(athlete_id: int, date: str)`
- `get_remaining_week_plan(athlete_id: int, week_start_date: str | None = None)`
- `get_today_remaining_sessions(athlete_id: int)`
- `get_next_planned_session(athlete_id: int, reference_date: str | None = None)`

Coach diario:

- `get_today_coach_briefing(athlete_id: int, reference_date: str | None = None)`
- `get_training_dashboard(athlete_id: int, reference_date: str | None = None)`
- `get_fatigue_risk_summary(athlete_id: int, reference_date: str | None = None)`

RAW metrics:

- `get_session_metrics_json(athlete_id: int, planned_session_id: int | None = None, activity_id: int | None = None, date: str | None = None)`
- `get_my_session_metrics_json(access_code: str, date: str | None = None, activity_id: int | None = None, planned_session_id: int | None = None)`
- `get_week_metrics_json(athlete_id: int, week_start_date: str | None = None, week_end_date: str | None = None, reference_date: str | None = None)`
- `get_my_week_metrics_json(access_code: str, week_start_date: str | None = None, week_end_date: str | None = None, reference_date: str | None = None)`

Importacion:

- `preview_plan_import(import_text: str)`
- `verify_plan_import(import_text: str)`
- `commit_plan_import(import_text: str, confirmation: str)`

V3C opcional:

- `get_next_session_decision(athlete_id: int, reference_date: str | None = None, planned_session_id: int | None = None)`
- `get_plan_adjustment_suggestions(athlete_id: int, reference_date: str | None = None)`
- `generate_plan_adjustment_import_text(athlete_id: int, adjustment_type: str, reference_date: str | None = None, planned_session_id: int | None = None, reason: str | None = None)`
- `get_my_fatigue_risk_summary(access_code: str, reference_date: str | None = None)` riesgo de fatiga por clave
- `get_week_strategy_summary(athlete_id: int, week_start_date: str | None = None)` estrategia de la semana
- `get_my_week_strategy_summary(access_code: str, week_start_date: str | None = None)` estrategia de la semana por clave
- `get_training_dashboard(athlete_id: int, reference_date: str | None = None)` panorama general compuesto
- `get_my_training_dashboard(access_code: str, reference_date: str | None = None)` panorama general compuesto por clave
- `get_plan_adjustment_suggestions(athlete_id: int, reference_date: str | None = None)` sugerencias read-only de ajuste
- `get_my_plan_adjustment_suggestions(access_code: str, reference_date: str | None = None)` sugerencias read-only de ajuste por clave
- `get_next_session_decision(athlete_id: int, reference_date: str | None = None, planned_session_id: int | None = None)` decision sobre proxima sesion
- `get_my_next_session_decision(access_code: str, reference_date: str | None = None, planned_session_id: int | None = None)` decision sobre proxima sesion por clave
- `get_optional_session_impact(athlete_id: int, planned_session_id: int | None = None, date: str | None = None, sport: str | None = None)` impacto de omitir una sesion
- `get_my_optional_session_impact(access_code: str, planned_session_id: int | None = None, date: str | None = None, sport: str | None = None)` impacto por clave
- `generate_plan_adjustment_import_text(athlete_id: int, adjustment_type: str, reference_date: str | None = None, planned_session_id: int | None = None, reason: str | None = None)` texto importable V2 sin aplicar
- `get_my_plan_adjustment_import_text(access_code: str, adjustment_type: str, reference_date: str | None = None, planned_session_id: int | None = None, reason: str | None = None)` texto importable V2 por clave
- `get_training_decision_context(athlete_id: int, reference_date: str | None = None)` contexto compuesto para decidir ajustes
- `get_my_training_decision_context(access_code: str, reference_date: str | None = None)` contexto compuesto por clave
- `get_session_metrics_json(athlete_id: int, planned_session_id: int | None = None, activity_id: int | None = None, date: str | None = None)`
- `get_my_session_metrics_json(access_code: str, date: str | None = None, activity_id: int | None = None, planned_session_id: int | None = None)`
- `get_session_block_analysis_payload(athlete_id: int, planned_session_id: int | None = None, activity_id: int | None = None, date: str | None = None)`
- `get_my_session_block_analysis_payload(access_code: str, date: str | None = None, activity_id: int | None = None, planned_session_id: int | None = None)`
- `preview_plan_import(import_text: str)`
- `verify_plan_import(import_text: str)`
- `commit_plan_import(import_text: str, confirmation: str)`

## Acceso experimental por atleta

Ademas de las tools admin/coach basadas en `athlete_id`, existe una capa experimental orientada al atleta con `access_code`.

- El atleta no necesita conocer `athlete_id`.
- Las tools `my_*` solo aceptan `access_code`.
- La API resuelve internamente el atleta y nunca permite consultar otro `athlete_id`.
- Todo sigue siendo read-only salvo las tools explicitas de plan import V2.
- Para preguntas de planificacion exacta como `Manana que sesion tengo` o `Que sesiones tengo esta semana`, conviene usar `get_my_day_plan` y `get_my_week_plan`.
- Si el atleta pregunta por una fecha concreta y queres mezclar planificacion + actividades Garmin del mismo dia, conviene usar `get_my_day_overview`.

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

## Nueva tool de dia exacto

`get_day_plan` y `get_my_day_plan` consultan `GET /api/mcp/training/day-plan` y `GET /api/mcp/me/day-plan`.

Devuelven un JSON read-only con:

- atleta, fecha y plan relevante
- `training_day` de la fecha exacta si existe
- `planned_sessions` del dia exacto
- `status` derivado por sesion: `planned`, `completed`, `no_activity`, `matched_with_activity`, `skipped` o `cancelled`
- `matched_activity` solo cuando existe una vinculacion explicita
- `summary` con mensaje claro cuando no hay nada programado

Reglas importantes:

- No reemplaza la fecha consultada por la proxima sesion pendiente.
- No mezcla una actividad Garmin cercana cuando la consulta pide una fecha exacta.
- Acepta `YYYY-MM-DD`, `DD-MM-YYYY` y `DD/MM/YYYY`.
- Si hay una sesion planificada sin actividad asociada, devuelve igualmente la planificacion del dia.

Prompt ejemplo:

- `Soy Pablo Scarone, mi clave de atleta es XXXX. Manana que sesion tengo?`
- `Que tengo el 20-05-2026?`
- `Que tengo el 20/05/2026?`

`get_week_plan` y `get_my_week_plan` consultan `GET /api/mcp/training/week-plan` y `GET /api/mcp/me/week-plan`.

Devuelven una vista read-only de 7 dias con:

- semana resuelta con `start_date` y `end_date`
- cada dia con `training_day`, `planned_sessions` y `summary`
- contadores de sesiones visibles, completadas y pendientes

Prompt ejemplo:

- `Que sesiones tengo esta semana`
- `Mostrame la semana que arranca el 2026-05-18`

`get_day_overview` y `get_my_day_overview` consultan `GET /api/mcp/training/day-overview` y `GET /api/mcp/me/day-overview`.

Devuelven un JSON read-only con:

- atleta y fecha resuelta
- `training_day` si existe
- `planned_sessions` del dia exacto
- `activities` Garmin del dia exacto
- `matches` cuando haya vinculacion explicita o coincidencia simple por fecha/deporte
- `summary` con mensaje claro cuando hay plan sin Garmin, Garmin sin plan o no hay datos

Reglas importantes:

- No reemplaza la fecha consultada por una actividad cercana.
- Acepta `YYYY-MM-DD` y tambien `DD-MM-YYYY`.
- Si hay una sesion planificada sin actividad asociada, devuelve igualmente la planificacion del dia.

Prompt ejemplo:

- `Soy Pablo Scarone, mi clave de atleta es XXXX. Que tengo para el 19-05-2026?`

Respuesta esperable:

- `Para el 19/05/2026 tenes programado Gimnasio suave, 45 minutos. No hay actividad Garmin asociada todavia.`

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
- actividades Garmin realizadas y sesiones planificadas
- sesiones manuales/completadas de gimnasio-fuerza sin actividad Garmin asociada
- carga total, distancia, duracion e intensidad
- promedio semanal de salud/readiness cuando haya datos
- weekly_analysis si existe
- comparacion con la semana previa

Campos utiles cuando preguntan por gym/fuerza:

- `week.garmin_activities_count`
- `week.completed_manual_sessions_count`
- `week.completed_strength_sessions_count`
- `week.total_completed_training_count`
- `manual_sessions`
- `summary.week_narrative`

La tool esta pensada para prompts como:

- `Como viene mi semana de carga`
- `Comparame esta semana con la anterior`
- `Estoy acumulando demasiada intensidad`
- `Dame un resumen de carga semanal del atleta 1`
- `Cuantas sesiones de gimnasio hice la semana pasada`

## Conversational V3

Las tools V3 agregan respuestas deterministicas para preguntas naturales sin obligar a navegar la UI. No usan IA generativa: solo derivan datos reales de `planned_sessions`, matches Garmin, sesiones manuales y estado de cancelacion.

Con `SESSION_TYPE` formal, V3 trata `required`, `race` y `test` como exigibles; `optional` y `recovery` no penalizan adherencia si quedan sin completar.

`get_remaining_week_plan` y `get_my_remaining_week_plan` consultan `GET /api/mcp/training/remaining-week-plan` y `GET /api/mcp/me/training/remaining-week-plan`.

Devuelven:

- `week_start_date` y `today`
- cantidad de `completed_sessions`
- cantidad de `remaining_sessions`
- cantidad de `required_sessions`
- cantidad de `optional_sessions`
- cantidad de `recovery_sessions`
- `remaining_volume_minutes`
- `total_remaining_minutes_required`
- `total_remaining_minutes_optional`
- `sessions` pendientes

Prompt ejemplo:

- `Que me queda esta semana?`

`get_previous_week_summary` y `get_my_previous_week_summary` consultan `GET /api/mcp/training/previous-week-summary` y `GET /api/mcp/me/training/previous-week-summary`.

Devuelven:

- sesiones realizadas por deporte
- `total_sessions`
- `total_duration_minutes`
- `adherence_percent`
- `completed_vs_planned`
- `highlights`

Prompt ejemplo:

- `Que hice la semana pasada?`

`get_next_planned_session` y `get_my_next_planned_session` consultan `GET /api/mcp/training/next-planned-session` y `GET /api/mcp/me/training/next-planned-session`.

Devuelven la proxima sesion pendiente ignorando canceladas y completadas, con `date`, `sport`, `name`, `duration_minutes`, `notes` y `blocks`.

Prompt ejemplo:

- `Que tengo manana?`
- `Que me toca despues?`

`get_today_remaining_sessions` y `get_my_today_remaining_sessions` consultan `GET /api/mcp/training/today-remaining-sessions` y `GET /api/mcp/me/training/today-remaining-sessions`.

Devuelven solo lo pendiente del dia actual del servidor.

Prompt ejemplo:

- `Me queda algo hoy?`

`get_week_adherence` y `get_my_week_adherence` consultan `GET /api/mcp/training/week-adherence` y `GET /api/mcp/me/training/week-adherence`.

Devuelven:

- `planned_sessions`
- `required_sessions`
- `optional_sessions`
- `recovery_sessions`
- `completed_sessions`
- `cancelled_sessions`
- `missed_sessions`
- `adherence_percent`
- `summary`

Regla:

- `adherence_percent = completed_sessions / required_sessions`

Prompt ejemplo:

- `Cumpli la semana?`

`get_today_coach_briefing` y `get_my_today_coach_briefing` consultan `GET /api/mcp/today-coach-briefing` y `GET /api/mcp/my/today-coach-briefing`.

Sirven para preguntas como:

- `Como estoy hoy?`
- `Dame el briefing del dia.`
- `Que tengo que hacer hoy?`
- `Me conviene entrenar?`
- `Que deberia mirar antes de entrenar?`

## Conversational V3B

Las tools V3B agregan comparaciones semanales, tendencia de carga, riesgo de fatiga, estrategia de semana y un dashboard compuesto. Siguen siendo read-only y deterministicas.

`get_week_comparison` y `get_my_week_comparison` consultan `GET /api/mcp/week-comparison` y `GET /api/mcp/me/week-comparison`.

Sirven para preguntas como:

- `Como fue esta semana contra la anterior?`
- `Hice mas o menos que la semana pasada?`

`get_training_load_trend` y `get_my_training_load_trend` consultan `GET /api/mcp/training-load-trend` y `GET /api/mcp/me/training-load-trend`.

Sirven para preguntas como:

- `Estoy subiendo la carga?`
- `Vengo acumulando mucho?`
- `Como viene la carga de las ultimas semanas?`

`get_fatigue_risk_summary` y `get_my_fatigue_risk_summary` consultan `GET /api/mcp/fatigue-risk-summary` y `GET /api/mcp/me/fatigue-risk-summary`.

Sirven para preguntas como:

- `Estoy acumulando fatiga?`
- `Conviene bajar algo?`
- `Estoy para meter intensidad?`

`get_week_strategy_summary` y `get_my_week_strategy_summary` consultan `GET /api/mcp/week-strategy-summary` y `GET /api/mcp/me/week-strategy-summary`.

Sirven para preguntas como:

- `Explicame esta semana.`
- `Que busca esta semana?`
- `Cual es la logica del plan?`

`get_training_dashboard` y `get_my_training_dashboard` consultan `GET /api/mcp/training-dashboard` y `GET /api/mcp/me/training-dashboard`.

Sirven para preguntas como:

- `Como estoy hoy?`
- `Dame panorama general.`
- `Que deberia mirar antes del proximo entreno?`

## Conversational V3C

Las tools V3C agregan ayuda de decision y ajuste de plan sin escribir en base. Cuando generan un `import_text`, es solo una propuesta compatible con V2 para usar despues con `preview_plan_import` y, si corresponde, `commit_plan_import`.

`get_plan_adjustment_suggestions` y `get_my_plan_adjustment_suggestions` consultan `GET /api/mcp/plan-adjustment-suggestions` y `GET /api/mcp/me/plan-adjustment-suggestions`.

Sirven para preguntas como:

- `Tengo que modificar algo esta semana?`
- `Tocarias algo de esta semana?`

`get_next_session_decision` y `get_my_next_session_decision` consultan `GET /api/mcp/next-session-decision` y `GET /api/mcp/me/next-session-decision`.

Sirven para preguntas como:

- `Mantengo el entrenamiento de manana?`
- `Que hago con la proxima sesion?`
- `Estoy para hacer intensidad?`

`get_optional_session_impact` y `get_my_optional_session_impact` consultan `GET /api/mcp/optional-session-impact` y `GET /api/mcp/me/optional-session-impact`.

Sirven para preguntas como:

- `Puedo saltear la bici?`
- `Que pasa si no hago la bici?`
- `Que pasa si cancelo esta sesion opcional?`

`generate_plan_adjustment_import_text` y `get_my_plan_adjustment_import_text` consultan `GET /api/mcp/generate-plan-adjustment-import-text` y `GET /api/mcp/me/generate-plan-adjustment-import-text`.

Sirven para preguntas como:

- `Generame el importable para cancelar la bici opcional.`
- `Armame el importable para bajar la sesion de manana.`
- `Proponeme el ajuste en formato importable.`

`get_training_decision_context` y `get_my_training_decision_context` consultan `GET /api/mcp/training-decision-context` y `GET /api/mcp/me/training-decision-context`.

Sirven para preguntas como:

- `Dame contexto para decidir.`
- `Que deberia mirar antes de tocar el plan?`

## Tool principal para sesiones

Para analisis conversacional de sesiones usar siempre `get_session_metrics_json`.

Las tools antiguas `get_activity_detail`, `compare_planned_vs_done` y `get_session_analysis_payload` quedan deprecated para MCP publico.

`get_session_metrics_json` consulta `GET /api/mcp/session-metrics-json` y devuelve un JSON read-only con:

- `planned_session`
- `activity`
- `metrics_json` completo del `SessionAnalysis`
- `limitations` claras si falta actividad, sesion o metrics

La tool esta pensada para prompts como:

- `Traeme el metrics_json de la sesion del 2026-05-15`
- `Analiza esta sesion usando el metrics_json guardado`
- `Mostrame block_analysis, structured_match y scores de la ultima actividad`

## Weekly RAW Metrics Mode

Para analisis semanal conversacional usar siempre `get_week_metrics_json`.

Las tools semanales narrativas o duplicadas como `get_latest_weekly_analysis` y `get_week_load_summary` quedan deprecated para MCP publico.

`get_week_metrics_json` consulta `GET /api/mcp/week-metrics-json` y devuelve un JSON read-only con:

- `week`
- `metrics_json_available`
- `metrics_json` completo
- `limitations`

La tool esta pensada para prompts como:

- `Traeme el weekly metrics_json de la ultima semana disponible`
- `Analiza esta semana usando el metrics_json guardado`
- `Mostrame totals, trends y scores de la semana del 2026-05-19`

## Tool legacy de payload tecnico

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

## Nueva tool de analisis fino por bloques

`get_session_block_analysis_payload` consulta `GET /api/mcp/session-block-analysis-payload` y devuelve un JSON read-only con:

- bloques planificados normalizados
- actividad Garmin resumida
- laps reales o laps disponibles en `metrics_json`
- matching bloque vs laps
- resumen global y limitaciones claras cuando falta granularidad

La tool esta pensada para prompts como:

- `Analiza la sesion del 29/05/26 por bloques`
- `En que bloque me pase de pulsaciones?`
- `Cumpli el bloque principal?`
- `Las recuperaciones bajaron lo suficiente?`

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
TRAINING_API_WRITE_TOKEN=change-me-write
TRAINING_API_ATHLETE_ID=

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
- `TRAINING_API_WRITE_TOKEN`: token bearer de escritura usado solo por `commit_plan_import`.
- `TRAINING_API_ATHLETE_ID`: fallback opcional. No pisa el `ATHLETE_ID` incluido en el bloque importable.
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
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/day-plan?athlete_id=1&date=2026-05-20"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/day-plan?athlete_id=1&date=20-05-2026"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/day-plan?athlete_id=1&date=20/05/2026"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/week-plan?athlete_id=1"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/week-plan?athlete_id=1&week_start_date=2026-05-18"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/week-plan?athlete_id=1&week_start_date=2026-05-18&include_completed=false"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/day-overview?athlete_id=1&date=2026-05-19"
curl -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/training/day-overview?athlete_id=1&date=19-05-2026"
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

### Plan import V2

`preview_plan_import` consulta `POST /api/mcp/plan-import/preview` y no escribe en DB.

`verify_plan_import` consulta `POST /api/mcp/plan-import/verify` y compara el bloque importable contra lo que realmente quedo en DB, sin aplicar cambios.

`commit_plan_import` consulta `POST /api/mcp/plan-import/commit`, exige `TRAINING_API_WRITE_TOKEN` y requiere `confirmation="APLICAR"`.

La importacion soporta `create`, `update`, `upsert` y `cancel`. Cancelar no borra fisicamente; marca la sesion como cancelada en la app principal.

`verify_plan_import` devuelve `valid=false` si faltan sesiones o si difieren campos clave. Si solo encuentra sesiones extra en la misma semana, devuelve `valid=true` con warnings.

Los bloques semanales deben incluir `ATHLETE_ID` y conviene incluir `ATHLETE_NAME`. Toda `SESSION` deberia declarar `SESSION_TYPE`:

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
NAME: Gimnasio suave

BLOCK
VALUE: 45
UNIT: min

END
```

`SESSION_TYPE` soporta `required`, `optional`, `recovery`, `race` y `test`.

Reglas practicas del importable:

- No importar dias de descanso como `SESSION`.
- No usar `SPORT: recovery`.
- Movilidad real: `SPORT: mobility` y `SESSION_TYPE: recovery`.
- Bici o gym opcional: `SESSION_TYPE: optional`.
- Fondo y sesiones clave: `SESSION_TYPE: required`.
- Carrera objetivo: `SESSION_TYPE: race`.
- Test controlado: `SESSION_TYPE: test`.

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
