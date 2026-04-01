from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError
from dataclasses import dataclass
import logging
import math
from pathlib import Path
import re
from typing import Any

import garth
from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectConnectionError

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


_PENDING_MFA_STATE: dict[str, dict[str, Any]] = {}
_RATE_LIMIT_STATE: dict[str, datetime] = {}
_TITLE_RE = re.compile(r"<title>(.+?)</title>", re.IGNORECASE | re.DOTALL)


def _pending_mfa_key(settings: Settings) -> str:
    return f"{settings.garmin_email or ''}|{Path(settings.garmin_token_dir).expanduser().resolve()}"


def _rate_limit_key(settings: Settings) -> str:
    return _pending_mfa_key(settings)


def _rate_limit_state_path(settings: Settings) -> Path:
    token_dir = Path(settings.garmin_token_dir).expanduser().resolve()
    return token_dir / "rate_limit_state.json"


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
    except (OSError, ValueError, TypeError):
        logger.warning("Could not read Garmin rate-limit state from %s", path, exc_info=True)
        return None

    until_raw = payload.get("until")
    if not until_raw:
        return None
    try:
        until = datetime.fromisoformat(str(until_raw))
    except ValueError:
        logger.warning("Garmin rate-limit state had an invalid timestamp: %s", until_raw)
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until


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


def get_garmin_auth_diagnostics(settings: Settings) -> dict[str, object]:
    token_dir = Path(settings.garmin_token_dir).expanduser().resolve()
    oauth1_token_path = token_dir / "oauth1_token.json"
    oauth2_token_path = token_dir / "oauth2_token.json"
    oauth1_exists = oauth1_token_path.exists()
    oauth2_exists = oauth2_token_path.exists()
    tokens_usable = _token_files_look_usable(oauth1_token_path, oauth2_token_path)
    remaining_rate_limit = _remaining_rate_limit_seconds(settings)
    rate_limit_until = _RATE_LIMIT_STATE.get(_rate_limit_key(settings))
    if rate_limit_until is not None:
        rate_limit_until_local = rate_limit_until.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    else:
        rate_limit_until_local = None

    return {
        "token_dir": str(token_dir),
        "oauth1_exists": oauth1_exists,
        "oauth2_exists": oauth2_exists,
        "tokens_usable": tokens_usable,
        "needs_mfa": has_pending_mfa(settings),
        "rate_limit_active": remaining_rate_limit is not None,
        "rate_limit_remaining_seconds": remaining_rate_limit,
        "rate_limit_until_local": rate_limit_until_local,
        "garmin_enabled": settings.garmin_enabled,
    }


def _token_files_look_usable(*paths: Path) -> bool:
    return all(path.exists() and path.is_file() and path.stat().st_size > 0 for path in paths)


def _delete_token_files(*paths: Path) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning("Could not remove Garmin token file %s", path, exc_info=True)


def _describe_last_response(client: Garmin) -> tuple[str, str | None]:
    response = getattr(client.garth, "last_resp", None)
    if response is None:
        return "No HTTP response details were available from Garmin.", None

    status = getattr(response, "status_code", None)
    content_type = response.headers.get("content-type", "")
    text = getattr(response, "text", "") or ""
    title_match = _TITLE_RE.search(text)
    title = title_match.group(1).strip() if title_match else None
    snippet = " ".join(text.split())[:240]

    parts = [f"status={status}", f"content_type={content_type or 'unknown'}"]
    if title:
        parts.append(f"title={title}")
    if snippet:
        parts.append(f"snippet={snippet}")
    return "; ".join(parts), title


def _looks_like_mfa_or_challenge(title: str | None, response_info: str) -> tuple[bool, bool]:
    text = f"{title or ''} {response_info}".upper()
    mfa_markers = (
        "MFA",
        "TWO-FACTOR",
        "TWO FACTOR",
        "VERIFICATION CODE",
        "ONE-TIME CODE",
        "VERIFYMFA",
        "SETUPENTERMFACODE",
        "ENTERMFACODE",
    )
    challenge_markers = (
        "SECURITY CHALLENGE",
        "VERIFY YOUR IDENTITY",
        "SUSPICIOUS",
        "CHALLENGE",
        "CAPTCHA",
        "BOT",
    )
    is_mfa = any(marker in text for marker in mfa_markers)
    is_challenge = any(marker in text for marker in challenge_markers)
    return is_mfa, is_challenge


def _looks_like_rate_limit(client: Garmin, exc: Exception) -> bool:
    response = getattr(client.garth, "last_resp", None)
    status = getattr(response, "status_code", None)
    if status == 429:
        return True
    text = str(exc).upper()
    return "429" in text or "TOO MANY REQUESTS" in text


def _raise_login_response_error(
    client: Garmin,
    settings: Settings,
    exc: Exception,
    *,
    base_message: str,
) -> None:
    response_info, html_title = _describe_last_response(client)
    is_mfa, is_challenge = _looks_like_mfa_or_challenge(html_title, response_info)

    logger.warning(
        "Garmin login returned an unexpected response. title=%s pending_mfa=%s debug=%s",
        html_title,
        has_pending_mfa(settings),
        response_info,
    )

    if is_mfa or has_pending_mfa(settings):
        raise GarminMFARequired(
            "Garmin requires MFA. Enter the verification code to continue the sync."
        ) from exc

    if is_challenge:
        raise GarminServiceError(
            "Garmin blocked the login with a security challenge. Open Garmin Connect in your browser, complete any verification it asks for, and then try the sync again. "
            f"Debug: {response_info}"
        ) from exc

    raise GarminServiceError(
        f"{base_message} Debug: {response_info}"
    ) from exc


def get_garmin_auth_context(settings: Settings, mfa_code: str | None = None) -> GarminAuthContext:
    if not settings.garmin_enabled:
        raise GarminServiceError("Garmin sync is disabled. Set GARMIN_ENABLED=true to use it.")

    if not settings.garmin_email or not settings.garmin_password:
        raise GarminServiceError("Garmin credentials are missing. Complete GARMIN_EMAIL and GARMIN_PASSWORD in .env.")

    token_dir = Path(settings.garmin_token_dir).expanduser().resolve()
    token_dir.mkdir(parents=True, exist_ok=True)
    oauth1_token_path = token_dir / "oauth1_token.json"
    oauth2_token_path = token_dir / "oauth2_token.json"
    pending_key = _pending_mfa_key(settings)

    remaining_rate_limit = _remaining_rate_limit_seconds(settings)
    if remaining_rate_limit is not None:
        wait_minutes = max(1, math.ceil(remaining_rate_limit / 60))
        raise GarminServiceError(
            f"Garmin esta limitando temporalmente el inicio de sesion. Espera {wait_minutes} min y volve a intentar. "
            "Si recien probaste varias veces, evita repetir intentos seguidos."
        )

    client = Garmin(
        settings.garmin_email,
        settings.garmin_password,
        prompt_mfa=None,
        return_on_mfa=True,
    )

    try:
        if _token_files_look_usable(oauth1_token_path, oauth2_token_path):
            login_result = client.login(str(token_dir))
        elif mfa_code:
            pending_state = _PENDING_MFA_STATE.get(pending_key)
            if pending_state is None:
                raise GarminServiceError("No Garmin MFA login is pending. Start the sync again before entering a code.")
            login_result = client.resume_login(pending_state, mfa_code.strip())
            _PENDING_MFA_STATE.pop(pending_key, None)
        else:
            if oauth1_token_path.exists() or oauth2_token_path.exists():
                logger.warning(
                    "Ignoring incomplete Garmin token files in %s and forcing a fresh login.",
                    token_dir,
                )
                _delete_token_files(oauth1_token_path, oauth2_token_path)
            login_result = client.login()

        if isinstance(login_result, tuple) and len(login_result) == 2 and login_result[0] == "needs_mfa":
            _PENDING_MFA_STATE[pending_key] = login_result[1]
            raise GarminMFARequired(
                "Garmin requires MFA. Enter the verification code to continue the sync."
            )
        _clear_rate_limit(settings)
    except (GarminConnectAuthenticationError, GarminConnectConnectionError) as exc:
        if _looks_like_rate_limit(client, exc):
            _mark_rate_limited(settings)
            raise GarminServiceError(
                "Garmin rechazo temporalmente el inicio de sesion por demasiados intentos (429 Too Many Requests). "
                "Espera unos minutos antes de volver a comparar o sincronizar."
            ) from exc
        message = str(exc)
        if "Expecting value: line 1 column 1 (char 0)" in message:
            _raise_login_response_error(
                client,
                settings,
                exc,
                base_message=(
                    "Garmin returned an unexpected login response. This usually means MFA, a security challenge, or a temporary change in Garmin login."
                ),
            )
        raise GarminServiceError(f"Garmin authentication failed: {exc}") from exc
    except JSONDecodeError as exc:
        if oauth1_token_path.exists() or oauth2_token_path.exists():
            logger.warning(
                "Garmin token files look corrupt or unreadable. Removing them and retrying a fresh login.",
                exc_info=True,
            )
            _delete_token_files(oauth1_token_path, oauth2_token_path)
            return get_garmin_auth_context(settings, mfa_code=mfa_code)
        _raise_login_response_error(
            client,
            settings,
            exc,
            base_message=(
                "Garmin returned an unexpected non-JSON response during login. This usually means MFA, a security challenge, or a temporary Garmin-side login change."
            ),
        )
    except Exception as exc:
        if _looks_like_rate_limit(client, exc):
            _mark_rate_limited(settings)
            raise GarminServiceError(
                "Garmin rechazo temporalmente el inicio de sesion por demasiados intentos (429 Too Many Requests). "
                "Espera unos minutos antes de volver a comparar o sincronizar."
            ) from exc
        raise GarminServiceError(f"Unexpected Garmin authentication error: {exc}") from exc

    try:
        garth.save(str(token_dir))
    except Exception:
        # Token persistence is best-effort; a successful session can still be used.
        pass

    return GarminAuthContext(client=client, token_dir=token_dir)
