from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.services.auth_context import require_admin_user
from app.services.local_db_sync_service import (
    LocalDbSyncError,
    is_local_db_sync_enabled,
    sync_vps_to_local,
    validate_local_db_sync_enabled,
)
from app.services.maintenance_service import (
    MaintenanceError,
    backup_download_name,
    create_database_backup,
    format_size,
    list_recent_backups,
    resolve_backup_file,
    sync_script_command,
    sync_script_exists,
)
from app.web.templates import build_templates


CONFIG_PATH = "/configuracion"
LEGACY_PATH = "/maintenance"

router = APIRouter(tags=["maintenance"])
templates = build_templates(Path(__file__).resolve().parent.parent)


def _redirect(
    url: str,
    *,
    status_message: str | None = None,
    error_message: str | None = None,
    extra_params: dict[str, str | None] | None = None,
) -> RedirectResponse:
    params: list[str] = []
    if status_message:
        params.append(f"status_message={quote(status_message)}")
    if error_message:
        params.append(f"error={quote(error_message)}")
    if extra_params:
        for key, value in extra_params.items():
            if value:
                params.append(f"{quote(key)}={quote(value)}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(url=f"{url}{suffix}", status_code=303)


@router.get(CONFIG_PATH, response_class=HTMLResponse)
def maintenance_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    require_admin_user(request, db)
    settings = get_settings()
    local_db_sync_enabled = is_local_db_sync_enabled(settings)
    local_db_sync_hint = None
    if not local_db_sync_enabled:
        try:
            validate_local_db_sync_enabled(settings)
        except LocalDbSyncError as exc:
            local_db_sync_hint = exc.message
    return templates.TemplateResponse(
        request=request,
        name="maintenance/index.html",
        context={
            "status_message": request.query_params.get("status_message"),
            "error_message": request.query_params.get("error"),
            "backups": [
                {
                    "filename": item.filename,
                    "size_label": format_size(item.size_bytes),
                    "created_at": item.created_at,
                }
                for item in list_recent_backups(limit=10)
            ],
            "sync_script_command": sync_script_command(),
            "sync_script_exists": sync_script_exists(),
            "local_db_sync_enabled": local_db_sync_enabled,
            "local_db_sync_hint": local_db_sync_hint,
            "sync_remote_backup_filename": request.query_params.get("remote_backup"),
            "sync_local_backup_filename": request.query_params.get("local_backup"),
            "sync_result_message": request.query_params.get("sync_result"),
        },
    )


@router.get(LEGACY_PATH)
def maintenance_legacy_redirect(request: Request) -> RedirectResponse:
    query = urlencode(list(request.query_params.multi_items()))
    suffix = f"?{query}" if query else ""
    return RedirectResponse(url=f"{CONFIG_PATH}{suffix}", status_code=307)


@router.post(f"{CONFIG_PATH}/database-backup")
@router.post(f"{LEGACY_PATH}/database-backup")
def maintenance_create_database_backup(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    require_admin_user(request, db)
    try:
        backup_path = create_database_backup()
    except MaintenanceError as exc:
        return _redirect(CONFIG_PATH, error_message=str(exc))
    return _redirect(CONFIG_PATH, status_message=f"Backup generado: {backup_path.name}")


@router.get(f"{CONFIG_PATH}/database-backup/download/{{filename}}")
@router.get(f"{LEGACY_PATH}/database-backup/download/{{filename}}")
def maintenance_download_database_backup(filename: str, request: Request, db: Session = Depends(get_db)) -> FileResponse:
    require_admin_user(request, db)
    try:
        backup_path = resolve_backup_file(filename)
    except MaintenanceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(
        path=backup_path,
        media_type="application/sql",
        filename=backup_download_name(backup_path),
    )


@router.post(f"{CONFIG_PATH}/sync-db-from-vps")
@router.post(f"{LEGACY_PATH}/sync-db-from-vps")
def maintenance_sync_db_from_vps(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    require_admin_user(request, db)
    settings = get_settings()
    try:
        validate_local_db_sync_enabled(settings)
        result = sync_vps_to_local(settings=settings)
    except LocalDbSyncError as exc:
        if exc.step in {"entorno", "configuracion", "configuraciÃ³n"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message) from exc
        return _redirect(CONFIG_PATH, error_message=f"{exc.step}: {exc.message}")
    return _redirect(
        CONFIG_PATH,
        status_message=result.message,
        extra_params={
            "remote_backup": result.remote_backup_filename,
            "local_backup": result.local_backup_filename,
            "sync_result": "Sincronizacion completada correctamente.",
        },
    )
