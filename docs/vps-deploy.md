# VPS Deploy

Guia de referencia para la configuracion actual de produccion/VPS de ProyectoGarmin. La idea es que el despliegue, la verificacion y la resolucion de problemas no dependan de memoria.

## 1. Arquitectura general

Flujo principal:

```text
ChatGPT / cliente MCP
-> https://proyectogarmin.dyndns.org/mcp
-> Nginx
-> training_mcp.service en 127.0.0.1:9000
-> API interna de la app /api/mcp
-> training_app.service en 127.0.0.1:8000
-> PostgreSQL
```

Resumen:

- La app web principal corre en `127.0.0.1:8000` con `training_app.service`.
- El servidor MCP remoto corre en `127.0.0.1:9000` con `training_mcp.service`.
- Nginx publica ambos servicios bajo el mismo dominio.
- HTTPS esta configurado con Certbot / Let's Encrypt.
- La base de datos de produccion es PostgreSQL.
- El endpoint MCP remoto publicado es `https://proyectogarmin.dyndns.org/mcp`.

## 2. Servicios systemd

### App principal

- Archivo: `/etc/systemd/system/training_app.service`
- Working directory: `/home/pablo/ProyectoGarmin`
- Comando:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Archivo de entorno usado por la app:

```text
/home/pablo/ProyectoGarmin/.env
```

### MCP

- Archivo: `/etc/systemd/system/training_mcp.service`
- Working directory: `/home/pablo/ProyectoGarmin`
- Comando:

```bash
python /home/pablo/ProyectoGarmin/mcp_training_server/server.py
```

- Archivo de entorno usado por el MCP:

```text
/home/pablo/ProyectoGarmin/mcp_training_server/.env
```

Importante:

- No usar el `.env` principal para el MCP.
- `app/config.py` es estricto y rechaza variables extra.
- Si se mezclan variables del MCP en el `.env` principal, la app puede fallar al iniciar con `ValidationError`.

## 3. Variables de entorno

Los valores reales no se commitean al repositorio.

- Los archivos `.env` deben quedar fuera de Git.
- Verificar que `.env` este incluido en `.gitignore`.

### `.env` principal de la app

Debe contener variables como:

```text
DATABASE_URL
GARMIN_ENABLED
GARMIN_EMAIL
GARMIN_PASSWORD
GARMIN_TOKEN_DIR
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_TIMEOUT_SEC
OPENAI_MAX_OUTPUT_TOKENS_SESSION
OPENAI_MAX_OUTPUT_TOKENS_WEEK
APP_NAME
DEBUG
MCP_API_TOKEN
```

No debe contener variables exclusivas del servidor MCP como:

```text
TRAINING_APP_BASE_URL
TRAINING_APP_MCP_TOKEN
MCP_TRANSPORT
MCP_HOST
MCP_PORT
MCP_HTTP_PATH
MCP_SSE_PATH
MCP_MESSAGE_PATH
```

### `.env` del MCP

Ubicacion:

```text
mcp_training_server/.env
```

Debe contener:

```dotenv
TRAINING_APP_BASE_URL=http://127.0.0.1:8000
TRAINING_APP_MCP_TOKEN=mismo_valor_que_MCP_API_TOKEN
MCP_TRANSPORT=http
MCP_HOST=127.0.0.1
MCP_PORT=9000
MCP_HTTP_PATH=/mcp
MCP_SSE_PATH=/sse
MCP_MESSAGE_PATH=/messages/
```

Notas:

- `TRAINING_APP_MCP_TOKEN` y `MCP_API_TOKEN` deben coincidir.
- El MCP consume la API interna de la app usando `http://127.0.0.1:8000`.

## 4. Nginx

Nginx publica:

- `/` -> `http://127.0.0.1:8000`
- `/mcp` -> `http://127.0.0.1:9000/mcp`

Ejemplo de bloque:

```nginx
server {
    listen 80;
    server_name proyectogarmin.dyndns.org;

    location /mcp {
        proxy_pass http://127.0.0.1:9000/mcp;
        proxy_http_version 1.1;
        proxy_set_header Host 127.0.0.1:9000;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Aclaracion:

- Certbot puede modificar o agregar automaticamente el bloque HTTPS.
- Eso incluye `listen 443 ssl`, paths de certificados y redireccion desde HTTP.

## 5. Comandos habituales de deploy

### Desde local

```bash
git add .
git commit -m "mensaje"
git push
```

### En el VPS

```bash
cd ~/ProyectoGarmin
git status
git restore .   # solo si hay cambios generados tipo __pycache__ o .pyc
git pull
source .venv/bin/activate
pip install -r requirements.txt
pip install -r mcp_training_server/requirements.txt
alembic upgrade head
sudo systemctl restart training_app
sudo systemctl restart training_mcp
```

Nota:

- Evitar `git restore .` si hay cambios manuales validos en produccion que todavia no fueron revisados.
- Usarlo solo para limpiar artefactos generados.

## 6. Comandos de verificacion

### App

```bash
sudo systemctl status training_app --no-pager -l
curl http://127.0.0.1:8000
```

### API MCP interna

```bash
curl -H "Authorization: Bearer TOKEN" http://127.0.0.1:8000/api/mcp/ping
```

### MCP local

```bash
curl -i -H "Accept: text/event-stream" http://127.0.0.1:9000/mcp
```

### MCP publico HTTPS

```bash
curl -i -H "Accept: text/event-stream" https://proyectogarmin.dyndns.org/mcp
```

### Servicios y logs

```bash
sudo systemctl status training_mcp --no-pager -l
sudo journalctl -u training_app -n 100 --no-pager -l
sudo journalctl -u training_mcp -n 100 --no-pager -l
```

## 7. Problemas conocidos y solucion

### 502 Bad Gateway

Posible causa:

- `training_app` o `training_mcp` caidos.

Revisar:

```bash
sudo systemctl status training_app --no-pager -l
sudo systemctl status training_mcp --no-pager -l
sudo journalctl -u training_app -n 100 --no-pager -l
sudo journalctl -u training_mcp -n 100 --no-pager -l
```

### Pydantic ValidationError: `Extra inputs are not permitted`

Significa:

- Variables del MCP fueron puestas en el `.env` principal.

Solucion:

- Mover esas variables a `mcp_training_server/.env`.
- Dejar el `.env` principal solo con variables de la app.

### MCP devuelve `421 Invalid Host header`

Significa:

- Nginx esta reenviando un `Host` que el servidor MCP no acepta.

Revisar en Nginx:

```nginx
proxy_set_header Host 127.0.0.1:9000;
```

### `curl /mcp` devuelve `Not Acceptable`

Significa:

- Falta el header correcto para el transporte HTTP/SSE del MCP.

Usar:

```bash
curl -i -H "Accept: text/event-stream" https://proyectogarmin.dyndns.org/mcp
```

### `curl -I /` devuelve `405`

Significa:

- No necesariamente es un error.
- La app puede no aceptar `HEAD`.

Probar con:

```bash
curl http://127.0.0.1:8000
```

## 8. Backup PostgreSQL

Comando:

```bash
mkdir -p ~/backups
pg_dump -U training_user -h localhost training_app > ~/backups/training_app_$(date +%F).sql
```

Sugerencia:

- Verificar periodicidad de backups y restauracion de prueba por separado.

## 9. Seguridad

- No commitear `.env`.
- Rotar `MCP_API_TOKEN` y `TRAINING_APP_MCP_TOKEN` si quedaron expuestos.
- Ambos tokens deben coincidir.
- Mantener HTTPS activo.
- No exponer PostgreSQL a internet.

## 10. Flujo recomendado de trabajo

Flujo principal:

```text
local VS Code + Codex
-> tests
-> git commit
-> git push
-> VPS git pull
-> restart services
```

Recomendacion:

- Evitar editar codigo directamente en produccion salvo hotfix.
- Si hubo hotfix en VPS, llevar ese cambio de vuelta al repo local cuanto antes.
