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
- Virtualenv: `/home/pablo/ProyectoGarmin/.venv`
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
- Virtualenv propia: `/home/pablo/ProyectoGarmin/mcp_training_server/.venv`
- Archivo de entorno usado por el MCP:

```text
/home/pablo/ProyectoGarmin/mcp_training_server/.env
```

- Unit file correcto:

```ini
[Unit]
Description=ProyectoGarmin MCP Server
After=network.target training_app.service
Requires=training_app.service

[Service]
User=pablo
Group=www-data
WorkingDirectory=/home/pablo/ProyectoGarmin
EnvironmentFile=/home/pablo/ProyectoGarmin/mcp_training_server/.env
Environment="PATH=/home/pablo/ProyectoGarmin/mcp_training_server/.venv/bin"
ExecStart=/home/pablo/ProyectoGarmin/mcp_training_server/.venv/bin/python /home/pablo/ProyectoGarmin/mcp_training_server/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Importante:

- No usar `/home/pablo/ProyectoGarmin/.venv/bin/python` para `training_mcp`.
- No usar `/home/pablo/ProyectoGarmin/.env` como `EnvironmentFile` del MCP.
- No usar el `.env` principal para el MCP.
- No usar la misma `.venv` para la app FastAPI y para `mcp_training_server`.
- `app/config.py` es estricto y rechaza variables extra.
- Si se mezclan variables del MCP en el `.env` principal, la app puede fallar al iniciar con `ValidationError`.
- Si se instala `mcp_training_server/requirements.txt` dentro de la `.venv` principal, la app puede romperse por conflicto de dependencias.

### Cambio real aplicado en produccion

Problema detectado:

- Se estaba usando la misma `.venv` para la app principal y para el MCP.
- `FastAPI 0.116.1` requiere `starlette < 0.48`.
- `mcp` / `sse-starlette` termino instalando `starlette 1.0.0`.
- Resultado: la app principal podia romperse despues de instalar dependencias del MCP.

Solucion aplicada:

- La app principal usa `/home/pablo/ProyectoGarmin/.venv`.
- El MCP usa `/home/pablo/ProyectoGarmin/mcp_training_server/.venv`.

Comandos para reparar o recrear esas venv:

```bash
cd ~/ProyectoGarmin
source .venv/bin/activate
pip install -r requirements.txt
deactivate

cd ~/ProyectoGarmin/mcp_training_server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
deactivate
```

## 3. Variables de entorno

Los valores reales no se commitean al repositorio.

- Los archivos `.env` deben quedar fuera de Git.
- Verificar que `.env` este incluido en `.gitignore`.

### `.env` principal de la app

Ubicacion:

```text
/home/pablo/ProyectoGarmin/.env
```

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
/home/pablo/ProyectoGarmin/mcp_training_server/.env
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
- No commitear tokens reales ni `.env` reales.

### Cambio real aplicado en produccion

Problema detectado:

- El `.env` principal de la app contenia variables del MCP.
- `app/config.py` usa Pydantic Settings estricto con `extra forbidden`.
- Resultado: la app principal caia con `pydantic_core.ValidationError: Extra inputs are not permitted`.

Solucion aplicada:

- El `.env` principal `/home/pablo/ProyectoGarmin/.env` debe contener solo variables de la app y `MCP_API_TOKEN`.
- El `.env` del MCP debe estar separado en `/home/pablo/ProyectoGarmin/mcp_training_server/.env`.

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
git pull

# app principal
source .venv/bin/activate
pip install -r requirements.txt
deactivate

# MCP
cd ~/ProyectoGarmin/mcp_training_server
source .venv/bin/activate
pip install -r requirements.txt
deactivate

cd ~/ProyectoGarmin
alembic upgrade head
sudo systemctl restart training_app
sudo systemctl restart training_mcp
```

Nota:

- No instalar `mcp_training_server/requirements.txt` dentro de `~/ProyectoGarmin/.venv`.
- Evitar `git restore .` si hay cambios manuales validos en produccion que todavia no fueron revisados.
- Usarlo solo para limpiar artefactos generados.

### Si se modifica el unit file de systemd

Despues de cambiar `/etc/systemd/system/training_mcp.service` o el de la app, correr:

```bash
sudo systemctl daemon-reload
sudo systemctl reset-failed training_app
sudo systemctl reset-failed training_mcp
sudo systemctl restart training_app
sudo systemctl restart training_mcp
```

## 6. Comandos de verificacion

### App

```bash
sudo systemctl status training_app --no-pager -l
curl http://127.0.0.1:8000
```

### API MCP interna

```bash
curl -H "Authorization: Bearer TOKEN" http://127.0.0.1:8000/api/mcp/ping
curl -H "Authorization: Bearer TOKEN" "http://127.0.0.1:8000/api/mcp/compare/planned-vs-done?athlete_id=1"
curl -H "Authorization: Bearer TOKEN" "http://127.0.0.1:8000/api/mcp/training/next-session-recommendation?athlete_id=1"
curl -H "Authorization: Bearer TOKEN" "http://127.0.0.1:8000/api/mcp/training/week-load-summary?athlete_id=1"
curl -H "Authorization: Bearer TOKEN" "http://127.0.0.1:8000/api/mcp/analysis/session-payload?athlete_id=1"
curl -H "Authorization: Bearer TOKEN" "http://127.0.0.1:8000/api/mcp/me/identify?access_code=CARO-7K92-XP31"
curl -H "Authorization: Bearer TOKEN" "http://127.0.0.1:8000/api/mcp/me/activities/recent?access_code=CARO-7K92-XP31&limit=5"
```

Prompt de prueba desde ChatGPT:

```text
Usando ProyectoGarmin, comparame la ultima actividad de Pablo Scarone con lo que tenia programado.
Usando ProyectoGarmin, dame una recomendacion para la proxima sesion de Pablo Scarone segun su estado actual.
Usando ProyectoGarmin, dame un resumen de carga semanal de Pablo Scarone y comparalo con la semana anterior.
Usando ProyectoGarmin, traeme el payload de analisis de la ultima actividad de Pablo y dame feedback tecnico por bloques.
```

### Acceso experimental por atleta

Existe una capa experimental para algunos atletas conocidos usando `access_code` privado.

- No reemplaza el acceso admin/coach actual con `athlete_id`.
- No requiere OAuth en esta etapa.
- El MCP sigue entrando por `https://proyectogarmin.dyndns.org/mcp`.
- Las tools nuevas `my_*` reciben `access_code` y la API interna resuelve el atleta.
- No se acepta `athlete_id` en esos endpoints `me`.

Crear una clave:

```bash
cd ~/ProyectoGarmin
source .venv/bin/activate
python ./scripts/create_athlete_access_code.py --athlete-id 2 --label "Carolina ChatGPT" --prefix CARO
deactivate
```

Crear una clave manual:

```bash
python ./scripts/create_athlete_access_code.py --athlete-id 2 --code CARO-TEST-1234 --label "Carolina ChatGPT"
```

Entrega:

- Entregar el `access_code` al atleta por un canal privado.
- El atleta puede decir en ChatGPT algo como:
  `Soy Carolina, mi clave de atleta es CARO-7K92-XP31`

Revocacion:

- Por ahora, desactivar el codigo directamente en la tabla `athlete_access_codes` poniendo `is_active=false`.
- No borrar historico si solo queres cortar acceso.

Advertencia:

- Esta V1 guarda `access_code` en texto plano por simplicidad experimental.
- No usar este enfoque con usuarios externos o no confiables.
- Si el alcance crece, migrar a hash, rotacion o un esquema con OAuth.

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
- Revisar que `TRAINING_APP_*` y `MCP_*` no esten en `/home/pablo/ProyectoGarmin/.env`.

### `pip install` del MCP rompio FastAPI / Starlette de la app

Significa:

- Se instalaron dependencias del MCP dentro de la `.venv` principal.

Solucion:

- Reinstalar la app en `~/ProyectoGarmin/.venv`.
- Mantener el MCP en `~/ProyectoGarmin/mcp_training_server/.venv`.

Verificar version Starlette de la app:

```bash
cd ~/ProyectoGarmin
source .venv/bin/activate
python -c "import starlette; print(starlette.__version__)"
deactivate
```

Debe ser compatible con FastAPI, por ejemplo `0.47.x`.

Verificar version Starlette del MCP:

```bash
cd ~/ProyectoGarmin/mcp_training_server
source .venv/bin/activate
python -c "import starlette; print(starlette.__version__)"
deactivate
```

Puede ser diferente porque usa venv separada.

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

### `training_mcp` sigue arrancando con la venv vieja

Revisar:

```bash
sudo cat /etc/systemd/system/training_mcp.service
```

Confirmar que `ExecStart` use:

```text
/home/pablo/ProyectoGarmin/mcp_training_server/.venv/bin/python
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
