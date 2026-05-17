from __future__ import annotations

from sqlalchemy.engine import make_url


def get_backend_name(database_url: str) -> str:
    return make_url(database_url).get_backend_name()


def is_sqlite_url(database_url: str) -> bool:
    return get_backend_name(database_url) == "sqlite"


def is_postgresql_url(database_url: str) -> bool:
    return get_backend_name(database_url) == "postgresql"
