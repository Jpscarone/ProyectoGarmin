from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from app.config import Settings


logger = logging.getLogger(__name__)


class GarminServiceError(Exception):
    """Raised when Garmin integration cannot complete safely."""


class GarminMFARequired(GarminServiceError):
    """Raised when Garmin requires an MFA code to continue login."""


@dataclass
class GarminAuthContext:
    client: Garmin
    token_dir: Path
    token_file: Path


_PENDING_MFA_STATE: dict[str, dict[str, Any]] = {}
_RATE_LIMIT_STATE: dict[str, datetime] = {}
_LAST_AUTH_ERROR: dict[str, str] = {}


def _pending_mfa_key(settings: Settings) -> str:
    return f"{settings.garmin_email or ''}|{Path(settings.garmin_token_dir).expanduser().resolve()}"


def _rate_limit_key(settings: Settings) -> str:
    return _pending_mfa_key(settings)


def _token_dir(settings: Settings) -> Path:
    return Path(settings.garmin_token_dir).expanduser().resolve()


def _token_file_path(settings: Settings) -> Path:
    return _token_dir(settings) / "garmin_tokens.json"


def _rate_limit_state_path(settings: Settings) -> Path:
    return _token_dir(settings) / "rate_limit_state.json"


def has_pending_mfa(settings: Settings) -> bool:
    return _pending_mfa_key(settings) in _PENDING_MFA_STATE


def clear_pending_mfa(settings: Settings) -> None:
    _PENDING_MFA_STATE.pop(_pending_mfa_key(settings), None)


def _mark_rate_limited(settings: Settings, minutes: int = 15) -> None:
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    _RATE_LIMIT_STATE[_rate_limit_key(settings)] = until
    _persist_rate_limit(settings, until)


def _clear_rate_limit(settings: Settings) -> None:
    _RATE_LIMIT_STATE.pop(_rate_limit_key(settings), None)
    _clear_persisted_rate_limit(settings)


def _persist_rate_limit(settings: Settings, until: datetime) -> None:
    path = _rate_limit_state_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"until": until.isoformat()}), encoding="utf-8")
    except OSError:
        logger.warning("Could not persist Garmin rate-limit state in %s", path, exc_info=True)


def _load_persisted_rate_limit(settings: Settings) -> datetime | None:
    path = _rate_limit_state_path(settings)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        until_raw = payload.get("until")
        if not until_raw:
            return None
        until = datetime.fromisoformat(str(until_raw))
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until
    except (OSError, TypeError, ValueError):
        logger.warning("Could not read Garmin rate-limit state from %s", path, exc_info=True)
        return None


def _clear_persisted_rate_limit(settings: Settings) -> None:
    path = _rate_limit_state_path(settings)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.warning("Could not remove Garmin rate-limit state file %s", path, exc_info=True)


def _remaining_rate_limit_seconds(settings: Settings) -> int | None:
    until = _RATE_LIMIT_STATE.get(_rate_limit_key(settings))
    if until is None:
        until = _load_persisted_rate_limit(settings)
        if until is not None:
            _RATE_LIMIT_STATE[_rate_limit_key(settings)] = until
    if until is None:
        return None
    remaining = int((until - datetime.now(timezone.utc)).total_seconds())
    if remaining <= 0:
        _clear_rate_limit(settings)
        return None
    return remaining


def _token_file_looks_usable(path: Path) -> bool:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    token_fields = (
        "di_token",
        "di_refresh_token",
        "it_token",
        "it_refresh_token",
        "jwt_web",
    )
    return any(bool(payload.get(field)) for field in token_fields)


def _delete_token_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.warning("Could not remove Garmin token file %s", path, exc_info=True)


def get_garmin_auth_diagnostics(settings: Settings) -> dict[str, object]:
    token_dir = _token_dir(settings)
    token_file = _token_file_path(settings)
    token_file_exists = token_file.exists()
    tokens_usable = _token_file_looks_usable(token_file)
    remaining_rate_limit = _remaining_rate_limit_seconds(settings)
    rate_limit_until = _RATE_LIMIT_STATE.get(_rate_limit_key(settings))
    rate_limit_until_local = (
        rate_limit_until.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        if rate_limit_until is not None
        else None
    )

    return {
        "token_dir": str(token_dir),
        "token_file": str(token_file),
        "token_file_exists": token_file_exists,
        "tokens_usable": tokens_usable,
        "needs_mfa": has_pending_mfa(settings),
        "rate_limit_active": remaining_rate_limit is not None,
        "rate_limit_remaining_seconds": remaining_rate_limit,
        "rate_limit_until_local": rate_limit_until_local,
        "garmin_enabled": settings.garmin_enabled,
        "last_auth_error": _LAST_AUTH_ERROR.get(_rate_limit_key(settings)),
        # Compatibilidad temporal con templates viejos
        "oauth1_exists": False,
        "oauth2_exists": token_file_exists,
    }


def _save_tokens(client: Garmin, token_dir: Path) -> None:
    try:
        client.client.dump(str(token_dir))
    except Exception:
        logger.warning("Could not persist Garmin tokens in %s", token_dir, exc_info=True)


def _clear_last_auth_error(settings: Settings) -> None:
    _LAST_AUTH_ERROR.pop(_rate_limit_key(settings), None)


def _remember_auth_error(settings: Settings, message: str) -> None:
    _LAST_AUTH_ERROR[_rate_limit_key(settings)] = message


def _new_garmin_client(settings: Settings) -> Garmin:
    return Garmin(
        settings.garmin_email,
        settings.garmin_password,
        prompt_mfa=None,
        return_on_mfa=True,
    )


def _raise_rate_limit(settings: Settings, exc: Exception) -> None:
    _mark_rate_limited(settings)
    _remember_auth_error(settings, str(exc))
    raise GarminServiceError(
        "Garmin rechazo temporalmente el inicio de sesion por demasiados intentos (429 Too Many Requests). "
        "Espera unos minutos antes de volver a comparar o sincronizar."
    ) from exc


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = ("429", "too many", "rate limit", "rate-limit")
    return any(marker in text for marker in markers)


def _complete_login_or_raise_mfa(
    settings: Settings,
    client: Garmin,
    token_dir: Path,
    login_callable,
) -> None:
    try:
        login_result = login_callable()
    except GarminConnectTooManyRequestsError as exc:
        _raise_rate_limit(settings, exc)
    except GarminConnectAuthenticationError as exc:
        if _is_rate_limit_error(exc):
            _raise_rate_limit(settings, exc)
        _remember_auth_error(settings, str(exc))
        raise GarminServiceError(f"Garmin authentication failed: {exc}") from exc
    except GarminConnectConnectionError as exc:
        if _is_rate_limit_error(exc):
            _raise_rate_limit(settings, exc)
        _remember_auth_error(settings, str(exc))
        raise GarminServiceError(f"Garmin connection failed: {exc}") from exc
    except Exception as exc:
        if _is_rate_limit_error(exc):
            _raise_rate_limit(settings, exc)
        _remember_auth_error(settings, str(exc))
        raise GarminServiceError(f"Unexpected Garmin authentication error: {exc}") from exc

    if isinstance(login_result, tuple) and login_result and login_result[0] == "needs_mfa":
        _PENDING_MFA_STATE[_pending_mfa_key(settings)] = {"client": client, "token_dir": str(token_dir)}
        raise GarminMFARequired(
            "Garmin requiere un codigo MFA para continuar. Ingresalo y volve a intentar."
        )

    clear_pending_mfa(settings)
    _clear_rate_limit(settings)
    _clear_last_auth_error(settings)
    _save_tokens(client, token_dir)


def get_garmin_auth_context(settings: Settings, mfa_code: str | None = None) -> GarminAuthContext:
    if not settings.garmin_enabled:
        raise GarminServiceError("Garmin sync is disabled. Set GARMIN_ENABLED=true to use it.")

    if not settings.garmin_email or not settings.garmin_password:
        raise GarminServiceError("Garmin credentials are missing. Complete GARMIN_EMAIL and GARMIN_PASSWORD in .env.")

    token_dir = _token_dir(settings)
    token_dir.mkdir(parents=True, exist_ok=True)
    token_file = _token_file_path(settings)

    remaining_rate_limit = _remaining_rate_limit_seconds(settings)
    if remaining_rate_limit is not None:
        wait_minutes = max(1, math.ceil(remaining_rate_limit / 60))
        raise GarminServiceError(
            f"Garmin esta limitando temporalmente el inicio de sesion. Espera {wait_minutes} min y volve a intentar. "
            "Si recien probaste varias veces, evita repetir intentos seguidos."
        )

    if mfa_code:
        pending_state = _PENDING_MFA_STATE.get(_pending_mfa_key(settings))
        pending_client = pending_state.get("client") if pending_state else None
        if not isinstance(pending_client, Garmin):
            raise GarminServiceError("No hay un login MFA pendiente para continuar.")
        _complete_login_or_raise_mfa(
            settings,
            pending_client,
            token_dir,
            lambda: pending_client.resume_login({}, mfa_code.strip()),
        )
        return GarminAuthContext(client=pending_client, token_dir=token_dir, token_file=token_file)

    client = _new_garmin_client(settings)

    if token_file.exists() and not _token_file_looks_usable(token_file):
        logger.warning("Garmin token file %s looks invalid. Removing it before login.", token_file)
        _delete_token_file(token_file)

    def _login() -> tuple[str | None, Any]:
        if token_file.exists():
            return client.login(str(token_dir))
        return client.login()

    _complete_login_or_raise_mfa(settings, client, token_dir, _login)

    return GarminAuthContext(client=client, token_dir=token_dir, token_file=token_file)
