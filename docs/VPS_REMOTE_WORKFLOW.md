# VPS Remote Workflow

Guia para desarrollar y desplegar directamente en el VPS usando VS Code Remote SSH, manteniendo Git como fuente de verdad y sin tocar configuracion sensible por accidente.

## Estructura Detectada

Raiz del proyecto detectada: `c:\Proyectos\Training_app`

Elementos relevantes presentes en este repo:

- `app/`
- `tests/`
- `scripts/`
- `requirements.txt`
- `alembic.ini`
- `migrations/`

Notas:

- No existe carpeta `alembic/` en la raiz; el repo usa `alembic.ini` + `migrations/`.
- Hay referencias documentadas a `training_app` y `training_mcp` en [docs/vps-deploy.md](/c:/Proyectos/Training_app/docs/vps-deploy.md), pero no se tocaron archivos reales de systemd.

## Flujo Recomendado En El VPS

1. Abrir VS Code.
2. Conectar con Remote SSH al servidor.
3. Abrir la carpeta del proyecto.
4. Antes de tocar nada:

```bash
git status
git pull --ff-only
```

5. Pedir cambios a Codex.
6. Ejecutar checks:

```bash
./scripts/check.sh
```

7. Reiniciar servicios:

```bash
./scripts/restart.sh
```

8. Ver logs:

```bash
./scripts/logs.sh
```

9. Cuando el cambio funcione, commitear:

```bash
./scripts/safe_commit.sh "descripcion del cambio" --push
```

## Flujo Para Actualizar La Copia Local

En tu PC local:

```bash
git pull
```

## Scripts Disponibles

### `./scripts/check.sh`

- Se mueve a la raiz del repo aunque lo lances desde otra carpeta.
- Activa `.venv`, `venv` o `env` si existe.
- Muestra el `python` usado y su version.
- Ejecuta:

```bash
python -m compileall app
python -m pytest
```

Si `pytest` no esta instalado, falla con mensaje claro.

### `./scripts/restart.sh`

- Reinicia `training_app` y `training_mcp`.
- Muestra `systemctl status --no-pager -l` de cada servicio.
- Si un servicio no existe o falta permiso, lo informa y sigue con el resto.

### `./scripts/logs.sh [lineas]`

- Muestra logs recientes de ambos servicios.
- Usa `120` lineas por defecto.

### `./scripts/app_logs.sh [lineas]`

- Muestra solo logs de `training_app`.

### `./scripts/mcp_logs.sh [lineas]`

- Muestra solo logs de `training_mcp`.

### `./scripts/deploy_local_vps.sh [--migrate]`

Uso pensado para ejecutar estando ya dentro del VPS.

Hace:

- valida que estas en un repo Git
- muestra rama actual y `git status`
- si hay cambios locales, corta antes del `pull`
- si no hay cambios, ejecuta `git pull --ff-only`
- activa virtualenv si existe
- ejecuta `alembic upgrade head` solo si pasas `--migrate`
- corre `./scripts/check.sh`
- reinicia servicios con `./scripts/restart.sh`
- muestra logs recientes de `training_app`

### `./scripts/safe_commit.sh "mensaje" [--push]`

Hace:

- muestra `git status`
- corre `./scripts/check.sh`
- si check falla, no commitea
- hace `git add .`
- hace `git commit -m "..."`
- hace `git push` solo si pasas `--push`

## Reglas De Seguridad

- No editar `.env` desde Codex salvo pedido explicito.
- No tocar credenciales ni claves SSH.
- No hacer cambios grandes sin commit.
- Cambio funcionando = commit.
- Si `git status` muestra cambios raros, detenerse y revisar.
- No ejecutar `alembic upgrade head` salvo que el cambio realmente lo requiera.

## VS Code Remote SSH

Ejemplo de configuracion local:

```sshconfig
Host training-vps
    HostName IP_DEL_SERVIDOR
    User USUARIO_DEL_VPS
    IdentityFile ~/.ssh/id_rsa
```

## Nota Sobre sudo

Si `./scripts/restart.sh` pide contrasena de `sudo`, esta bien.

Opcionalmente podrias restringir permisos con `sudoers`, pero no se configuro nada automaticamente. Si algun dia lo queres hacer, usar `visudo` y un archivo dedicado en `/etc/sudoers.d/`.

Ejemplo documentado, no aplicar sin revisar:

```sudoers
USUARIO_DEL_VPS ALL=NOPASSWD: /bin/systemctl restart training_app
USUARIO_DEL_VPS ALL=NOPASSWD: /bin/systemctl restart training_mcp
USUARIO_DEL_VPS ALL=NOPASSWD: /bin/systemctl status training_app *
USUARIO_DEL_VPS ALL=NOPASSWD: /bin/systemctl status training_mcp *
USUARIO_DEL_VPS ALL=NOPASSWD: /bin/journalctl -u training_app *
USUARIO_DEL_VPS ALL=NOPASSWD: /bin/journalctl -u training_mcp *
```

## Comandos De Uso Rapido

```bash
chmod +x scripts/*.sh
./scripts/check.sh
./scripts/restart.sh
./scripts/logs.sh
./scripts/safe_commit.sh "configuro flujo remote ssh vps" --push
```
