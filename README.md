# training_app

Base tecnica inicial de una aplicacion web en Python con FastAPI, SQLAlchemy, Alembic, Jinja2 y SQLite.

## Requisitos

- Python 3.12

## Crear entorno virtual

### PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### CMD

```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
```

## Instalar dependencias

```powershell
pip install -r requirements.txt
```

## Configurar variables de entorno

```powershell
Copy-Item .env.example .env
```

Variables Garmin minimas:

- `GARMIN_ENABLED=true` para habilitar la sincronizacion manual
- `GARMIN_EMAIL=tu_correo_garmin`
- `GARMIN_PASSWORD=tu_password_garmin`
- `GARMIN_TOKEN_DIR=./.garmin_tokens`

## Correr migraciones

Aplicar la migracion base:

```powershell
alembic upgrade head
```

Crear una nueva migracion en el futuro:

```powershell
alembic revision --autogenerate -m "descripcion"
```

## Ejecutar la aplicacion

```powershell
uvicorn app.main:app --reload
```

Abrir en el navegador:

`http://127.0.0.1:8000`

## Sincronizacion Garmin

La integracion usa la libreria no oficial `garminconnect` y guarda tokens de sesion en el directorio configurado por `GARMIN_TOKEN_DIR`.

Flujo recomendado:

1. completar las variables Garmin en `.env`
2. ejecutar migraciones
3. levantar la app
4. entrar a `/sync/garmin/activities`
5. lanzar la sincronizacion manual

Si el login inicial requiere renovar la sesion, la libreria intentara guardar tokens en `GARMIN_TOKEN_DIR` para reutilizarlos en los siguientes syncs.

## Estructura

```text
training_app/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── models/
│   ├── routers/
│   ├── schemas/
│   ├── services/
│   ├── templates/
│   └── static/
├── migrations/
├── requirements.txt
├── alembic.ini
├── .env.example
└── README.md
```
