from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.athlete import Athlete
from app.db.models.athlete_access_code import AthleteAccessCode


ACCESS_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def normalize_access_code(value: str) -> str:
    normalized = (value or "").strip().upper()
    if not normalized:
        raise ValueError("La clave de acceso no puede estar vacia.")
    return normalized


def generate_access_code(*, prefix: str | None = None) -> str:
    chunks = [
        "".join(secrets.choice(ACCESS_CODE_ALPHABET) for _ in range(4)),
        "".join(secrets.choice(ACCESS_CODE_ALPHABET) for _ in range(4)),
    ]
    normalized_prefix = _normalize_prefix(prefix)
    if normalized_prefix:
        return "-".join([normalized_prefix, *chunks])
    return "-".join(chunks)


def create_athlete_access_code(
    db: Session,
    *,
    athlete: Athlete,
    label: str | None = None,
    code: str | None = None,
    prefix: str | None = None,
    notes: str | None = None,
) -> AthleteAccessCode:
    access_code = normalize_access_code(code) if code else _generate_unique_access_code(db, prefix=prefix)
    existing = db.scalar(select(AthleteAccessCode).where(AthleteAccessCode.access_code == access_code))
    if existing is not None:
        raise ValueError("La clave de acceso ya existe. Usa otra o vuelve a generar.")
    row = AthleteAccessCode(
        athlete_id=athlete.id,
        access_code=access_code,
        label=(label or "").strip() or None,
        is_active=True,
        notes=(notes or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve_athlete_by_access_code(access_code: str, db: Session) -> Athlete:
    normalized = normalize_access_code(access_code)
    row = db.scalar(
        select(AthleteAccessCode)
        .where(
            AthleteAccessCode.access_code == normalized,
            AthleteAccessCode.is_active.is_(True),
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clave de acceso invalida.",
        )
    athlete = db.get(Athlete, row.athlete_id)
    if athlete is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clave de acceso invalida.",
        )
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return athlete


def _generate_unique_access_code(db: Session, *, prefix: str | None = None) -> str:
    for _ in range(20):
        candidate = generate_access_code(prefix=prefix)
        existing = db.scalar(select(AthleteAccessCode.id).where(AthleteAccessCode.access_code == candidate))
        if existing is None:
            return candidate
    raise ValueError("No se pudo generar una clave unica. Intenta nuevamente.")


def _normalize_prefix(value: str | None) -> str | None:
    normalized = (value or "").strip().upper().replace(" ", "")
    if not normalized:
        return None
    filtered = "".join(char for char in normalized if char.isalnum())
    return filtered or None
