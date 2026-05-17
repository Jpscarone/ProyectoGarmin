from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.engine import make_url

from app.config import Settings, get_settings
from app.db.url import is_postgresql_url
from app.services.maintenance_service import get_backup_dir


SAFE_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1"}


class LocalDbSyncError(RuntimeError):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step
        self.message = message


@dataclass(slots=True)
class LocalDbTarget:
    host: str
    port: int
    database: str
    app_user: str
    app_password: str | None
    admin_user: str
    admin_password: str | None


@dataclass(slots=True)
class LocalDbSyncResult:
    remote_backup_filename: str
    local_backup_filename: str
    downloaded_backup_path: Path
    local_backup_path: Path
    message: str


def is_local_db_sync_enabled(settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    try:
        validate_local_db_sync_enabled(current)
    except LocalDbSyncError:
        return False
    return True


def validate_local_db_sync_enabled(settings: Settings | None = None) -> None:
    current = settings or get_settings()
    if current.app_env != "local":
        raise LocalDbSyncError("entorno", "La sincronización VPS → Local solo está habilitada cuando APP_ENV=local.")
    if not current.enable_local_db_sync:
        raise LocalDbSyncError("entorno", "La sincronización VPS → Local requiere ENABLE_LOCAL_DB_SYNC=true.")
    if not (current.vps_sync_host or "").strip():
        raise LocalDbSyncError("configuración", "Falta configurar VPS_SYNC_HOST para habilitar la sincronización.")
    _local_db_target(current)


def build_remote_backup_filename(settings: Settings | None = None, *, now: datetime | None = None) -> str:
    current = settings or get_settings()
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M")
    return f"{timestamp}_{current.project_backup_prefix}_VPS_{current.local_db_name}.sql"


def build_local_pre_sync_backup_filename(settings: Settings | None = None, *, now: datetime | None = None) -> str:
    current = settings or get_settings()
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M")
    return f"{timestamp}_{current.project_backup_prefix}_LOCAL_pre_sync_{current.local_db_name}.sql"


def sync_vps_to_local(*, settings: Settings | None = None, now: datetime | None = None) -> LocalDbSyncResult:
    current = settings or get_settings()
    validate_local_db_sync_enabled(current)
    _ensure_tools_available()
    timestamp = now or datetime.now()
    remote_backup_filename = build_remote_backup_filename(current, now=timestamp)
    local_backup_filename = build_local_pre_sync_backup_filename(current, now=timestamp)

    downloaded_backup_path = download_remote_dump(
        settings=current,
        filename=remote_backup_filename,
    )
    local_backup_path = create_local_pre_sync_backup(
        settings=current,
        filename=local_backup_filename,
    )
    recreate_local_database(settings=current)
    restore_dump_to_local(downloaded_backup_path, settings=current)
    run_alembic_upgrade(settings=current)

    return LocalDbSyncResult(
        remote_backup_filename=remote_backup_filename,
        local_backup_filename=local_backup_filename,
        downloaded_backup_path=downloaded_backup_path,
        local_backup_path=local_backup_path,
        message="Base local actualizada con datos del VPS",
    )


def create_remote_vps_dump(*, settings: Settings | None = None, filename: str) -> str:
    current = settings or get_settings()
    validate_local_db_sync_enabled(current)
    remote_path = str(PurePosixPath(current.vps_sync_remote_backup_dir) / filename)
    command = _ssh_base_command(current)
    if current.vps_sync_remote_db_password:
        command.extend(["env", f"PGPASSWORD={current.vps_sync_remote_db_password}"])
    command.extend(
        [
            "pg_dump",
            "--format=plain",
            "--no-owner",
            "--no-privileges",
            "--file",
            remote_path,
            "--host",
            "localhost",
            "--username",
            current.vps_sync_remote_db_user,
            current.vps_sync_remote_db_name,
        ]
    )
    _run_command("pg_dump remoto", command)
    return remote_path


def download_remote_dump(*, settings: Settings | None = None, filename: str) -> Path:
    current = settings or get_settings()
    remote_path = create_remote_vps_dump(settings=current, filename=filename)
    local_path = get_backup_dir() / filename
    command = [
        "scp",
        "-P",
        str(current.vps_sync_ssh_port),
        f"{current.vps_sync_user}@{current.vps_sync_host}:{remote_path}",
        str(local_path),
    ]
    _run_command("descarga scp", command)
    if not local_path.is_file():
        raise LocalDbSyncError("descarga scp", "La descarga terminó sin dejar el archivo del dump en var/backups/.")
    _cleanup_remote_dump(remote_path, current)
    return local_path


def create_local_pre_sync_backup(*, settings: Settings | None = None, filename: str) -> Path:
    current = settings or get_settings()
    target = _local_db_target(current)
    backup_path = get_backup_dir() / filename
    command = [
        "pg_dump",
        "--file",
        str(backup_path),
        "--format=plain",
        "--no-owner",
        "--no-privileges",
        "--host",
        target.host,
        "--port",
        str(target.port),
        "--username",
        target.app_user,
        target.database,
    ]
    _run_command("backup local", command, env=_postgres_env(target.app_password))
    if not backup_path.is_file():
        raise LocalDbSyncError("backup local", "El backup preventivo local no se generó en disco.")
    return backup_path


def recreate_local_database(*, settings: Settings | None = None) -> None:
    current = settings or get_settings()
    target = _local_db_target(current)
    admin_env = _postgres_env(target.admin_password)
    base_command = [
        "psql",
        "--host",
        target.host,
        "--port",
        str(target.port),
        "--username",
        target.admin_user,
        "--dbname",
        "postgres",
        "--command",
    ]
    _run_command(
        "recreate local DB",
        base_command
        + [
            (
                "SELECT pg_terminate_backend(pid) "
                f"FROM pg_stat_activity WHERE datname = '{target.database}' AND pid <> pg_backend_pid();"
            )
        ],
        env=admin_env,
    )
    _run_command(
        "recreate local DB",
        base_command + [f"DROP DATABASE IF EXISTS {target.database};"],
        env=admin_env,
    )
    _run_command(
        "recreate local DB",
        base_command + [f"CREATE DATABASE {target.database} OWNER {target.app_user};"],
        env=admin_env,
    )


def restore_dump_to_local(dump_path: Path, *, settings: Settings | None = None) -> None:
    current = settings or get_settings()
    target = _local_db_target(current)
    command = [
        "psql",
        "--host",
        target.host,
        "--port",
        str(target.port),
        "--username",
        target.app_user,
        "--dbname",
        target.database,
        "--file",
        str(dump_path),
    ]
    _run_command("restore", command, env=_postgres_env(target.app_password))


def run_alembic_upgrade(*, settings: Settings | None = None) -> None:
    current = settings or get_settings()
    env = dict(os.environ)
    env["DATABASE_URL"] = current.database_url
    command = [sys.executable, "-m", "alembic", "upgrade", "head"]
    _run_command("alembic", command, env=env)


def _ensure_tools_available() -> None:
    for tool_name, step in (
        ("ssh", "SSH"),
        ("scp", "descarga scp"),
        ("pg_dump", "backup local"),
        ("psql", "recreate local DB"),
    ):
        if not shutil.which(tool_name):
            raise LocalDbSyncError(step, f"{tool_name} no está disponible en el sistema o no está en PATH.")


def _ssh_base_command(settings: Settings) -> list[str]:
    return [
        "ssh",
        "-p",
        str(settings.vps_sync_ssh_port),
        f"{settings.vps_sync_user}@{settings.vps_sync_host}",
    ]


def _cleanup_remote_dump(remote_path: str, settings: Settings) -> None:
    command = _ssh_base_command(settings) + ["rm", "-f", remote_path]
    try:
        subprocess.run(command, check=False, capture_output=True, text=True)
    except Exception:
        return


def _local_db_target(settings: Settings) -> LocalDbTarget:
    if not is_postgresql_url(settings.database_url):
        raise LocalDbSyncError("configuración", "DATABASE_URL debe apuntar a PostgreSQL para habilitar la sincronización.")
    url = make_url(settings.database_url)
    host = str(url.host or "").strip().lower()
    if host not in SAFE_LOCAL_DB_HOSTS:
        raise LocalDbSyncError(
            "configuración",
            "DATABASE_URL no apunta a localhost o 127.0.0.1. La sincronización quedó bloqueada por seguridad.",
        )
    database_name = str(url.database or "").strip()
    if database_name != settings.local_db_name:
        raise LocalDbSyncError(
            "configuración",
            "DATABASE_URL y LOCAL_DB_NAME no coinciden. La sincronización quedó bloqueada por seguridad.",
        )
    return LocalDbTarget(
        host=host,
        port=int(url.port or 5432),
        database=database_name,
        app_user=str(url.username or settings.local_db_user),
        app_password=str(url.password) if url.password is not None else settings.local_db_password,
        admin_user=settings.local_admin_db_user,
        admin_password=settings.local_admin_db_password,
    )


def _postgres_env(password: str | None) -> dict[str, str] | None:
    if not password:
        return None
    env = dict(os.environ)
    env["PGPASSWORD"] = password
    return env


def _run_command(step: str, command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise LocalDbSyncError(step, f"No se pudo ejecutar el paso {step}: {command[0]} no está disponible.") from exc
    if completed.returncode != 0:
        detail = _sanitize_error_output(
            completed.stderr or completed.stdout or f"El comando terminó con código {completed.returncode}.",
            env=env,
        )
        raise LocalDbSyncError(step, f"Falló el paso {step}: {detail}")
    return completed


def _sanitize_error_output(message: str, *, env: dict[str, str] | None = None) -> str:
    cleaned = " ".join((message or "").split())
    current = get_settings()
    secrets = [
        current.vps_sync_remote_db_password,
        current.local_db_password,
        current.local_admin_db_password,
        make_url(current.database_url).password if is_postgresql_url(current.database_url) else None,
        env.get("PGPASSWORD") if env else None,
    ]
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "***")
    cleaned = cleaned.replace(current.database_url, _redact_database_url(current.database_url))
    return cleaned[:500]


def _redact_database_url(database_url: str) -> str:
    try:
        parts = urlsplit(database_url)
    except Exception:
        return "postgresql://***"
    netloc = parts.netloc
    if "@" in netloc and ":" in netloc.split("@", 1)[0]:
        credentials, host = netloc.split("@", 1)
        username = credentials.split(":", 1)[0]
        netloc = f"{username}:***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
