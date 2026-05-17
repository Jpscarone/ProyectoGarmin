# PostgreSQL Local En Windows

Esta guia deja el entorno local de `training_app` usando PostgreSQL, con el mismo enfoque general que el VPS: `DATABASE_URL` por variable de entorno, migraciones Alembic sobre PostgreSQL y sin depender de `SQLite` en el flujo normal de desarrollo.

## 1. Instalar PostgreSQL

Instala PostgreSQL para Windows desde el instalador oficial:

- `https://www.postgresql.org/download/windows/`

Durante la instalacion:

- recorda la password del usuario administrador `postgres`
- deja habilitado `psql`
- usa el puerto por defecto `5432` salvo que ya tengas otro PostgreSQL corriendo

Despues de instalar, abrí una nueva terminal PowerShell y verificá:

```powershell
psql --version
```

## 2. Crear usuario y base local

Entrá con el usuario administrador:

```powershell
psql -U postgres -h localhost
```

Crear usuario y base:

```sql
CREATE USER training_user WITH PASSWORD 'TU_PASSWORD';
CREATE DATABASE training_app OWNER training_user;
GRANT ALL PRIVILEGES ON DATABASE training_app TO training_user;
```

Salir de `psql`:

```sql
\q
```

## 3. Configurar `.env`

Si todavía no existe:

```powershell
Copy-Item .env.example .env
```

Configurar la URL local:

```dotenv
DATABASE_URL=postgresql://training_user:TU_PASSWORD@localhost/training_app
```

Importante:

- no usar `sqlite:///...` en desarrollo normal
- mantener `.env` fuera de Git
- el VPS puede seguir usando su propio `.env` con otra URL PostgreSQL

## 4. Instalar dependencias Python

```powershell
pip install -r requirements.txt
```

El proyecto ahora incluye `psycopg[binary]`, que es el driver usado por SQLAlchemy para conectarse a PostgreSQL en Windows.

## 5. Verificar conexion

```powershell
python scripts/check_db_connection.py
```

Si la conexion falla, revisar:

- que PostgreSQL este corriendo como servicio
- que `training_user` exista
- que la password del `.env` coincida
- que el puerto y host sean correctos

## 6. Aplicar migraciones

Con la base vacia:

```powershell
alembic upgrade head
```

Para crear migraciones nuevas en adelante:

```powershell
alembic revision --autogenerate -m "descripcion"
```

## 7. Levantar la app local

```powershell
uvicorn app.main:app --reload
```

## 8. Resetear la base local de desarrollo

Script disponible:

```powershell
python scripts/reset_local_postgres_db.py
```

Advertencia:

- este script elimina y recrea la base configurada en `DATABASE_URL`
- no se ejecuta sin confirmacion explicita, salvo que uses `--yes`

Despues del reset:

```powershell
alembic upgrade head
```

## 9. Flujo recomendado

Local:

```text
desarrollo -> alembic upgrade head -> pruebas -> git push
```

VPS:

```text
git pull -> pip install -r requirements.txt -> alembic upgrade head -> restart
```

Con este esquema, local y VPS usan PostgreSQL y comparten las mismas migraciones Alembic.
