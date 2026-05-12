# MCP Training Server V1B

## Que hace

Este servidor MCP expone herramientas de solo lectura para consultar tu Training System desde un cliente MCP.
No crea, no edita, no borra, no sincroniza Garmin y no dispara analisis nuevos.

Internamente consume la API MCP read-only que ya existe en la app principal FastAPI.

## Herramientas expuestas

- `get_session_feedback_by_date(date: str)`
- `get_week_context()`
- `get_last_activity_feedback()`
- `get_next_session_context()`

## Requisitos

- Python 3.10+
- La app principal corriendo
- Variables de entorno configuradas

## Instalacion

### PowerShell

Desde la raiz del repo:

```powershell
python -m venv .\mcp_training_server\.venv
.\mcp_training_server\.venv\Scripts\Activate.ps1
python -m pip install -r .\mcp_training_server\requirements.txt
```

## Configuracion

Copiá `.env.example` a `.env` y completá el token:

```env
TRAINING_API_URL=http://localhost:8000
TRAINING_API_TOKEN=change-me
# Opcional si hay multiples atletas activos en la API principal
# TRAINING_API_ATHLETE_ID=1

MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=9000
MCP_HTTP_PATH=/mcp
MCP_SSE_PATH=/sse
MCP_MESSAGE_PATH=/messages/
```

### PowerShell

```powershell
Copy-Item .\mcp_training_server\.env.example .\mcp_training_server\.env
notepad .\mcp_training_server\.env
```

Variables:

- `TRAINING_API_URL`: base URL de la app principal
- `TRAINING_API_TOKEN`: token Bearer que la app principal espera para `/api/mcp/*`
- `TRAINING_API_ATHLETE_ID`: opcional. Recomendado cuando la API principal tiene mas de un atleta activo y necesita contexto explicito.
- `MCP_TRANSPORT`: `stdio`, `http` o `sse`
- `MCP_HOST`: host para el modo remoto
- `MCP_PORT`: puerto para el modo remoto
- `MCP_HTTP_PATH`: path para streamable HTTP, por defecto `/mcp`
- `MCP_SSE_PATH`: path para SSE, por defecto `/sse`
- `MCP_MESSAGE_PATH`: path de mensajes SSE, por defecto `/messages/`

## Flujo recomendado de validacion

### 1. Levantar la API principal con token MCP

Desde la raiz del repo:

```powershell
$env:MCP_API_TOKEN = "change-me"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. Probar la API MCP principal

Con el token correcto:

```powershell
curl.exe -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/week-context?athlete_id=1"
curl.exe -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/last-activity-feedback?athlete_id=1"
curl.exe -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/next-session-context?athlete_id=1"
curl.exe -H "Authorization: Bearer change-me" "http://127.0.0.1:8000/api/mcp/session-feedback?athlete_id=1&date=2026-05-02"
```

Con token incorrecto:

```powershell
curl.exe -H "Authorization: Bearer wrong-token" "http://127.0.0.1:8000/api/mcp/week-context?athlete_id=1"
```

Smoke test rapido:

```powershell
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\smoke_test_api.py
```

### 3. Correr el servidor MCP

Desde la raiz del repo:

```powershell
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\server.py
```

El servidor usa el SDK oficial de MCP para Python con `FastMCP` y corre por `stdio`, ideal para clientes MCP locales.

### 3A. Correr en modo stdio

```powershell
$env:MCP_TRANSPORT = "stdio"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\server.py
```

### 3B. Correr en modo remoto HTTP

```powershell
$env:MCP_TRANSPORT = "http"
$env:MCP_HOST = "0.0.0.0"
$env:MCP_PORT = "9000"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\server.py
```

URL local esperada:

```text
http://127.0.0.1:9000/mcp
```

### 3C. Correr en modo remoto SSE

```powershell
$env:MCP_TRANSPORT = "sse"
$env:MCP_HOST = "0.0.0.0"
$env:MCP_PORT = "9000"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\server.py
```

### 4. Probar con MCP Inspector

```powershell
.\mcp_training_server\.venv\Scripts\Activate.ps1
npx -y @modelcontextprotocol/inspector
```

En el Inspector, configurá un servidor `stdio` con:

- Command: `C:\Proyectos\Training_app\mcp_training_server\.venv\Scripts\python.exe`
- Args: `C:\Proyectos\Training_app\mcp_training_server\server.py`
- Working directory: `C:\Proyectos\Training_app`

Para remoto HTTP en Inspector, podés usar:

- URL: `http://127.0.0.1:9000/mcp`

## Exponer por HTTPS

ChatGPT necesita una URL publica HTTPS para conectarse al MCP remoto.

### Opcion 1: ngrok

```powershell
ngrok http 9000
```

Usá la URL `https://...ngrok-free.app/mcp`

### Opcion 2: Cloudflare Tunnel

```powershell
cloudflared tunnel --url http://127.0.0.1:9000
```

Usá la URL `https://...trycloudflare.com/mcp`

## Crear el conector en ChatGPT

1. Abrí ChatGPT.
2. Andá a `Settings`.
3. Entrá en `Connectors` o `Apps`.
4. Elegí `Create`.
5. Pegá la URL HTTPS publica del MCP remoto.
6. Si usás streamable HTTP, la URL debe terminar en `/mcp`.

Ejemplo:

```text
https://tu-subdominio.ngrok-free.app/mcp
```

## Smoke tests

### Smoke test API

```powershell
$env:TRAINING_API_URL = "http://127.0.0.1:8000"
$env:TRAINING_API_TOKEN = "change-me"
$env:TRAINING_API_ATHLETE_ID = "1"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\smoke_test_api.py
```

### Smoke test remoto MCP

Primero levantá el server remoto:

```powershell
$env:MCP_TRANSPORT = "http"
$env:MCP_HOST = "127.0.0.1"
$env:MCP_PORT = "9000"
python .\mcp_training_server\server.py
```

En otra consola:

```powershell
$env:MCP_REMOTE_URL = "http://127.0.0.1:9000/mcp"
.\mcp_training_server\.venv\Scripts\Activate.ps1
python .\mcp_training_server\smoke_test_remote.py
```

## Como funciona

Las herramientas llaman estos endpoints de la API principal:

- `GET /api/mcp/session-feedback?date=YYYY-MM-DD`
- `GET /api/mcp/week-context`
- `GET /api/mcp/last-activity-feedback`
- `GET /api/mcp/next-session-context`

## Errores manejados

- Si falta `TRAINING_API_TOKEN`, devuelve un error claro.
- Si la API responde `401`, informa que el token es invalido o falta.
- Si la API no esta disponible, informa que no se pudo conectar al sistema de entrenamiento.
- Si la API responde `404` o `500+`, devuelve un error legible sin exponer secretos.

## Ejemplos de preguntas en un cliente MCP

- "¿Cómo me salió la sesión del miércoles?"
- "Analizá mi última actividad."
- "¿Cómo viene la semana?"
- "¿Mantengo el entrenamiento de mañana?"

## Ejemplo de uso esperado

- Para una fecha concreta, el cliente MCP puede llamar `get_session_feedback_by_date("2026-05-06")`.
- Tambien acepta `get_session_feedback_by_date("02/05/26")` o `get_session_feedback_by_date("02/05/2026")`.
- Para revisar la semana, puede llamar `get_week_context()`.
- Para revisar lo ultimo hecho, puede llamar `get_last_activity_feedback()`.
- Para decidir mañana, puede llamar `get_next_session_context()`.
