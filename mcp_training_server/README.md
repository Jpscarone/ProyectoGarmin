# ProyectoGarmin MCP Server

## Que hace

Este servidor MCP remoto consume la API interna read-only de ProyectoGarmin bajo `/api/mcp` y expone tools para consultar atletas, actividades, salud y estado de entrenamiento.

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
