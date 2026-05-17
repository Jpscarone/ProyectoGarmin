# Mantenimiento

La seccion `Mantenimiento` esta disponible solo para usuarios con rol `admin`.

## Backup desde la web

1. Ingresar a `Mantenimiento`.
2. En la card `Backup de base de datos`, hacer clic en `Crear backup de BD`.
3. Confirmar la accion.
4. Si `pg_dump` esta disponible y la conexion PostgreSQL es valida, el sistema genera un archivo `.sql`.

## Donde se guardan los backups

- Carpeta: `var/backups/`
- Formato de nombre:
  `YYYYMMDD_HHMM_ProyectoGarmin_training_app.sql`
- Ejemplo:
  `20260517_2135_ProyectoGarmin_training_app.sql`

La pantalla lista los ultimos 10 backups disponibles, con tamano, fecha y enlace de descarga.

## Como descargarlos

- Desde la misma pantalla de `Mantenimiento`, usar `Descargar`.
- La descarga esta protegida para admins y valida el nombre del archivo para evitar path traversal.

## Restauracion manual de un backup

La restauracion no se ejecuta desde la web. Debe hacerse manualmente desde consola sobre el entorno correcto.

Ejemplo general:

```powershell
psql -h <host> -p <puerto> -U <usuario> -d <base_destino> -f .\var\backups\20260517_2135_ProyectoGarmin_training_app.sql
```

Antes de restaurar:

- Confirmar que el destino sea la base correcta.
- Verificar permisos del usuario PostgreSQL.
- Evaluar impacto sobre sesiones activas o procesos que esten usando la base.

## Emparejar BD VPS -> Local

El boton `Traer BD desde VPS` ejecuta una sincronizacion manual solo en entorno local.

### Que hace

1. Genera un dump de la base del VPS por `ssh` + `pg_dump`.
2. Descarga ese dump al entorno local con `scp`.
3. Crea un backup preventivo de la base local.
4. Termina conexiones activas sobre la base local.
5. Hace `DROP DATABASE` y `CREATE DATABASE` en la base local.
6. Restaura el dump del VPS en la base local.
7. Ejecuta `alembic upgrade head`.

### Requisitos

La accion solo se habilita si se cumplen todas estas condiciones:

- `APP_ENV=local`
- `ENABLE_LOCAL_DB_SYNC=true`
- `VPS_SYNC_HOST` configurado
- `DATABASE_URL` apuntando a `localhost` o `127.0.0.1`
- `DATABASE_URL` usando PostgreSQL

Si cualquiera de esas validaciones falla:

- el boton no se muestra
- el endpoint backend devuelve `403`

### Variables de entorno

Configurar en `.env`:

```dotenv
APP_ENV=local
ENABLE_LOCAL_DB_SYNC=true
VPS_SYNC_HOST=
VPS_SYNC_USER=pablo
VPS_SYNC_SSH_PORT=22
VPS_SYNC_REMOTE_DB_NAME=training_app
VPS_SYNC_REMOTE_DB_USER=training_user
VPS_SYNC_REMOTE_DB_PASSWORD=
VPS_SYNC_REMOTE_BACKUP_DIR=/home/pablo
LOCAL_DB_NAME=training_app
LOCAL_DB_USER=training_user
LOCAL_DB_PASSWORD=
LOCAL_ADMIN_DB_USER=postgres
LOCAL_ADMIN_DB_PASSWORD=
PROJECT_BACKUP_PREFIX=ProyectoGarmin
```

No se muestran contrasenas ni URLs completas con password en la interfaz.

### Advertencia

Esta accion borra y reemplaza la base local. No modifica la base del VPS, pero si destruye el contenido actual de tu base local.

### Como verificar que solo esta habilitado en local

- En `Mantenimiento`, el boton debe aparecer solo cuando `APP_ENV=local` y `ENABLE_LOCAL_DB_SYNC=true`.
- En produccion o en el VPS, la card muestra solo texto informativo.
- Si alguien llama `POST /maintenance/sync-db-from-vps` fuera de ese contexto, el backend responde `403`.

### Archivos generados

- Dump descargado desde el VPS:
  `YYYYMMDD_HHMM_ProyectoGarmin_VPS_training_app.sql`
- Backup preventivo local:
  `YYYYMMDD_HHMM_ProyectoGarmin_LOCAL_pre_sync_training_app.sql`

Ambos quedan en `var/backups/`.

### Como restaurar el backup local preventivo

Si la sincronizacion falla y necesitas volver al estado anterior de la base local:

```powershell
psql -h localhost -U <LOCAL_DB_USER> -d <LOCAL_DB_NAME> -f .\var\backups\YYYYMMDD_HHMM_ProyectoGarmin_LOCAL_pre_sync_training_app.sql
```

Antes de hacerlo:

- recrea la base local si quedo a medio camino
- confirma que el archivo sea el backup preventivo correcto
- verifica que estas apuntando a la base local

## Advertencias de seguridad

- La visibilidad del menu y las rutas backend estan restringidas a usuarios `admin`.
- La sincronizacion VPS -> Local nunca debe habilitarse en produccion.
- Las acciones potencialmente riesgosas requieren confirmacion antes de ejecutarse.
- Si `pg_dump`, `psql`, `ssh` o `scp` no estan en `PATH`, la web muestra un error claro y no continua.
