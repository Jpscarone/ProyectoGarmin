from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    """
                    SELECT
                        current_database() AS database_name,
                        current_user AS database_user,
                        version() AS server_version
                    """
                )
            ).mappings().one()
    except Exception as exc:
        print(f"Database connection failed: {exc}")
        return 1
    finally:
        engine.dispose()

    print("Database connection OK")
    print(f"Database: {result['database_name']}")
    print(f"User: {result['database_user']}")
    print(f"Version: {result['server_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
