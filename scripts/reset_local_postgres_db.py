from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.db.url import is_postgresql_url

SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _build_admin_url(database_url: str) -> URL:
    url = make_url(database_url)
    return url.set(database="postgres")


def _validate_identifier(value: str, label: str) -> str:
    if not SAFE_IDENTIFIER_RE.fullmatch(value):
        raise SystemExit(f"{label} contains unsupported characters: {value!r}")
    return value


def _confirm(database_name: str) -> None:
    prompt = (
        f"This will DROP and recreate the local PostgreSQL database {database_name!r}. "
        "Type RESET to continue: "
    )
    if input(prompt).strip() != "RESET":
        raise SystemExit("Cancelled.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drop and recreate the local PostgreSQL development database defined by DATABASE_URL."
    )
    parser.add_argument("--database-url", help="Override DATABASE_URL for this run.")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt.")
    args = parser.parse_args()

    database_url = args.database_url or get_settings().database_url
    if not is_postgresql_url(database_url):
        raise SystemExit("This reset script only supports PostgreSQL DATABASE_URL values.")

    target_url = make_url(database_url)
    database_name = _validate_identifier(target_url.database or "", "Database name")
    owner_name = _validate_identifier(target_url.username or "", "Database owner")

    if not args.yes:
        _confirm(database_name)

    admin_engine = create_engine(
        _build_admin_url(database_url),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )

    try:
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
            connection.execute(text(f'CREATE DATABASE "{database_name}" OWNER "{owner_name}"'))
    except Exception as exc:
        print(f"Database reset failed: {exc}")
        return 1
    finally:
        admin_engine.dispose()

    print(f"Database {database_name!r} recreated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
