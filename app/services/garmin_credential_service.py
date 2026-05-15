from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.athlete import Athlete
from app.db.models.garmin_account import GarminAccount
from app.services.security import GarminCredentialBundle


logger = logging.getLogger(__name__)

GARMIN_FALLBACK_SOURCE = "deprecated_global_env"
GARMIN_ACCOUNT_SOURCE = "athlete_account"


class GarminCredentialConfigurationError(ValueError):
    pass


class GarminCredentialDecryptError(ValueError):
    pass


class GarminCredentialMissingError(ValueError):
    pass


def default_token_dir_for_athlete(athlete_id: int) -> str:
    return str((Path("var") / "garmin_tokens" / f"athlete_{athlete_id}").resolve())


def encrypt_garmin_password(password: str, secret_key: str | None) -> str:
    if not password:
        raise ValueError("La contraseña Garmin no puede estar vacía.")
    fernet = _build_fernet(secret_key)
    return fernet.encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_garmin_password(ciphertext: str, secret_key: str | None) -> str:
    fernet = _build_fernet(secret_key)
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        logger.warning("Failed to decrypt Garmin credentials; athlete reconfiguration required")
        raise GarminCredentialDecryptError(
            "No se pudieron descifrar las credenciales Garmin guardadas. Reconfigurá la cuenta Garmin del atleta."
        ) from exc


def get_or_create_garmin_account(db: Session, athlete: Athlete) -> GarminAccount:
    account = next(iter(athlete.garmin_accounts), None) if getattr(athlete, "garmin_accounts", None) else None
    if account is not None:
        if not account.token_dir:
            account.token_dir = default_token_dir_for_athlete(athlete.id)
            db.add(account)
            db.commit()
            db.refresh(account)
        return account
    account = GarminAccount(
        athlete_id=athlete.id,
        token_dir=default_token_dir_for_athlete(athlete.id),
        is_active=True,
        status="active",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def resolve_garmin_credentials(settings: Settings, athlete: Athlete, account: GarminAccount | None) -> GarminCredentialBundle | None:
    if account is not None and account.is_active and account.garmin_email and account.garmin_password_encrypted:
        return GarminCredentialBundle(
            email=account.garmin_email,
            password=decrypt_garmin_password(account.garmin_password_encrypted, settings.garmin_credential_secret_key),
            token_dir=account.token_dir or default_token_dir_for_athlete(athlete.id),
            source=GARMIN_ACCOUNT_SOURCE,
        )

    if not settings.garmin_global_fallback_enabled:
        return None

    if settings.garmin_email and settings.garmin_password:
        logger.warning("Deprecated Garmin global fallback used athlete_id=%s", athlete.id)
        return GarminCredentialBundle(
            email=settings.garmin_email,
            password=settings.garmin_password,
            token_dir=settings.garmin_token_dir,
            source=GARMIN_FALLBACK_SOURCE,
        )
    return None


def _build_fernet(secret_key: str | None):
    normalized = (secret_key or "").strip()
    if not normalized:
        raise GarminCredentialConfigurationError(
            "GARMIN_CREDENTIAL_SECRET_KEY no está configurada. Definila antes de guardar o usar credenciales Garmin."
        )
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise GarminCredentialConfigurationError(
            "Falta la dependencia cryptography. Instalá requirements.txt antes de usar credenciales Garmin."
        ) from exc
    try:
        return Fernet(normalized.encode("utf-8"))
    except Exception as exc:
        raise GarminCredentialConfigurationError(
            "GARMIN_CREDENTIAL_SECRET_KEY no tiene un formato Fernet válido."
        ) from exc
