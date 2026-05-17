from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db.url import is_postgresql_url


BACKUP_DIR = Path("var/backups")
PROJECT_BACKUP_SUFFIX = "training_app"
SYNC_SCRIPT_PATH = Path("scripts/sync_db_from_vps.ps1")


class MaintenanceError(RuntimeError):
    pass


@dataclass(slots=True)
class BackupFileInfo:
    filename: str
    size_bytes: int
    created_at: datetime


def get_backup_dir() -> Path:
    backup_dir = BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def build_backup_filename(now: datetime | None = None) -> str:
    settings = get_settings()
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M")
    return f"{timestamp}_{settings.project_backup_prefix}_{PROJECT_BACKUP_SUFFIX}.sql"


def resolve_backup_file(filename: str) -> Path:
    candidate = Path(filename)
    if candidate.name != filename or filename in {"", ".", ".."}:
        raise MaintenanceError("Nombre de archivo de backup inválido.")
    backup_path = (get_backup_dir() / candidate.name).resolve()
    backup_dir = get_backup_dir().resolve()
    if backup_dir not in backup_path.parents:
        raise MaintenanceError("Nombre de archivo de backup inválido.")
    if not backup_path.is_file():
        raise MaintenanceError("El backup solicitado no existe.")
    return backup_path


def list_recent_backups(limit: int = 10) -> list[BackupFileInfo]:
    backup_dir = get_backup_dir()
    files = [path for path in backup_dir.glob("*.sql") if path.is_file()]
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    rows: list[BackupFileInfo] = []
    for path in files[:limit]:
        stat = path.stat()
        rows.append(
            BackupFileInfo(
                filename=path.name,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime),
            )
        )
    return rows


def backup_download_name(path: Path) -> str:
    return path.name


def format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size_bytes)} B"


def sync_script_exists() -> bool:
    return SYNC_SCRIPT_PATH.is_file()


def sync_script_command() -> str:
    return r".\scripts\sync_db_from_vps.ps1"


def create_database_backup(*, now: datetime | None = None) -> Path:
    settings = get_settings()
    database_url = settings.database_url
    if not is_postgresql_url(database_url):
        raise MaintenanceError("El backup web solo está disponible para bases PostgreSQL.")

    pg_dump_path = shutil.which("pg_dump")
    if not pg_dump_path:
        raise MaintenanceError("pg_dump no está disponible en el sistema o no está en PATH")

    url = make_url(database_url)
    filename = build_backup_filename(now=now)
    backup_path = get_backup_dir() / filename

    command = [
        pg_dump_path,
        "--file",
        str(backup_path),
        "--format=plain",
        "--no-owner",
        "--no-privileges",
        "--host",
        str(url.host or "localhost"),
        "--port",
        str(url.port or 5432),
        "--username",
        str(url.username or ""),
        str(url.database or ""),
    ]
    env = None
    if url.password:
        env = dict(os.environ, PGPASSWORD=str(url.password))

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise MaintenanceError("pg_dump no está disponible en el sistema o no está en PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        combined = stderr or stdout
        if combined:
            raise MaintenanceError(f"No se pudo crear el backup de PostgreSQL: {combined}") from exc
        raise MaintenanceError("No se pudo crear el backup de PostgreSQL.") from exc

    if not backup_path.is_file():
        raise MaintenanceError("El backup terminó sin generar archivo en disco.")
    return backup_path
