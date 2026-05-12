"""
Usage:
    python scripts/migrate_sqlite_to_postgres.py \
        --sqlite-path ./training_app.db \
        --postgres-url postgresql+psycopg://user:password@host:5432/dbname

    python scripts/migrate_sqlite_to_postgres.py \
        --sqlite-path ./training_app.db \
        --postgres-url postgresql+psycopg://user:password@host:5432/dbname \
        --dry-run

    python scripts/migrate_sqlite_to_postgres.py \
        --sqlite-path ./training_app.db \
        --postgres-url postgresql+psycopg://user:password@host:5432/dbname \
        --truncate

Notes:
    - Migrates data only. It does not create or modify schema objects.
    - Preserves original primary key values when possible.
    - Skips rows whose primary key already exists in PostgreSQL.
    - Use --dry-run to inspect tables, order, and counts without writing data.
    - Use --truncate only when you explicitly want to clear destination tables first.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import MetaData, and_, bindparam, create_engine, func, inspect, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql.compiler import IdentifierPreparer

INTERNAL_TABLES = {"alembic_version", "sqlite_sequence"}
MAX_TABLE_WARNINGS = 10


@dataclass
class TableSummary:
    table: str
    source_count: int = 0
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate data from a local SQLite database to an existing PostgreSQL schema.",
    )
    parser.add_argument("--sqlite-path", required=True, help="Path to the SQLite database file.")
    parser.add_argument("--postgres-url", required=True, help="PostgreSQL SQLAlchemy URL.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and simulate migration without writing data.")
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate destination tables before migrating data. Disabled by default.",
    )
    return parser.parse_args()


def normalize_table_names(table_names: list[str]) -> list[str]:
    return sorted(table for table in table_names if table not in INTERNAL_TABLES)


def build_dependency_order(pg_engine: Engine, tables: list[str]) -> tuple[list[str], list[str], dict[str, set[str]]]:
    inspector = inspect(pg_engine)
    table_set = set(tables)
    dependencies: dict[str, set[str]] = {}

    for table in tables:
        deps = set()
        for fk in inspector.get_foreign_keys(table):
            referred_table = fk.get("referred_table")
            if referred_table and referred_table in table_set and referred_table != table:
                deps.add(referred_table)
        dependencies[table] = deps

    pending = {table: set(deps) for table, deps in dependencies.items()}
    ordered: list[str] = []

    while pending:
        ready = sorted(table for table, deps in pending.items() if not deps)
        if not ready:
            break
        ordered.extend(ready)
        resolved = set(ready)
        pending = {
            table: (deps - resolved)
            for table, deps in pending.items()
            if table not in resolved
        }

    cyclic = sorted(pending)
    ordered.extend(cyclic)
    return ordered, cyclic, dependencies


def detect_deferred_cycle_columns(pg_engine: Engine, cyclic_tables: list[str]) -> dict[str, set[str]]:
    inspector = inspect(pg_engine)
    cyclic_set = set(cyclic_tables)
    deferred: dict[str, set[str]] = defaultdict(set)

    for table in cyclic_tables:
        column_info = {column["name"]: column for column in inspector.get_columns(table)}
        for fk in inspector.get_foreign_keys(table):
            referred_table = fk.get("referred_table")
            constrained_columns = fk.get("constrained_columns") or []
            if not referred_table or referred_table not in cyclic_set:
                continue
            if constrained_columns and all(column_info[column]["nullable"] for column in constrained_columns):
                deferred[table].update(constrained_columns)

    return deferred


def load_table(engine: Engine, table_name: str) -> tuple[MetaData, object]:
    metadata = MetaData()
    metadata.reflect(bind=engine, only=[table_name])
    return metadata, metadata.tables[table_name]


def has_server_default(column: dict) -> bool:
    return bool(column.get("default") is not None or column.get("identity") is not None)


def format_column_list(columns: list[str]) -> str:
    return ", ".join(columns) if columns else "(none)"


def quote_table_name(preparer: IdentifierPreparer, table_name: str) -> str:
    return preparer.quote(table_name)


def add_warning(warnings: dict[str, list[str]], table_name: str, message: str) -> None:
    entries = warnings[table_name]
    if message in entries:
        return
    if len(entries) < MAX_TABLE_WARNINGS:
        entries.append(message)
        return
    overflow_message = f"Additional warnings omitted after {MAX_TABLE_WARNINGS} entries."
    if overflow_message not in entries:
        entries.append(overflow_message)


def truncate_tables(pg_conn: Connection, table_names: list[str]) -> None:
    if not table_names:
        return
    preparer = IdentifierPreparer(pg_conn.dialect)
    quoted_tables = ", ".join(quote_table_name(preparer, table) for table in table_names)
    pg_conn.execute(text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE"))


def build_pk_exists_statement(dest_table, pk_columns: list[str]):
    if not pk_columns:
        return None
    return (
        select(*[dest_table.c[column] for column in pk_columns])
        .where(and_(*[dest_table.c[column] == bindparam(f"pk_{column}") for column in pk_columns]))
        .limit(1)
    )


def migrate_table(
    table_name: str,
    sqlite_conn: Connection,
    pg_conn: Connection,
    dry_run: bool,
    warnings: dict[str, list[str]],
    deferred_columns: set[str] | None = None,
) -> tuple[TableSummary, list[dict[str, object]]]:
    _, source_table = load_table(sqlite_conn.engine, table_name)
    _, dest_table = load_table(pg_conn.engine, table_name)

    deferred_columns = deferred_columns or set()
    source_columns = {column.name for column in source_table.columns}
    dest_columns = {column.name for column in dest_table.columns}
    common_columns = [
        column.name
        for column in dest_table.columns
        if column.name in source_columns and column.name not in deferred_columns
    ]
    summary = TableSummary(table=table_name)
    inserted_pk_rows: list[dict[str, object]] = []

    summary.source_count = sqlite_conn.execute(select(func.count()).select_from(source_table)).scalar_one()
    ignored_columns = sorted(source_columns - dest_columns)
    if ignored_columns:
        add_warning(
            warnings,
            table_name,
            f"SQLite columns ignored because they do not exist in PostgreSQL: {format_column_list(ignored_columns)}"
        )

    pg_inspector = inspect(pg_conn)
    dest_column_info = {column["name"]: column for column in pg_inspector.get_columns(table_name)}
    missing_dest_columns = sorted(dest_columns - source_columns)
    optional_missing = []
    required_missing = []
    for column_name in missing_dest_columns:
        column_info = dest_column_info[column_name]
        if column_info.get("nullable") or has_server_default(column_info):
            optional_missing.append(column_name)
        else:
            required_missing.append(column_name)

    if optional_missing:
        add_warning(
            warnings,
            table_name,
            f"PostgreSQL columns missing in SQLite will be left unset: {format_column_list(optional_missing)}"
        )

    if required_missing:
        add_warning(
            warnings,
            table_name,
            f"Required PostgreSQL columns missing in SQLite may cause row errors: {format_column_list(required_missing)}"
        )
    if deferred_columns:
        add_warning(
            warnings,
            table_name,
            f"Deferred nullable cycle columns for a second pass update: {format_column_list(sorted(deferred_columns))}"
        )

    pk_columns = [column.name for column in dest_table.primary_key.columns]
    insert_stmt = pg_insert(dest_table)
    if pk_columns:
        insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=pk_columns)

    pk_exists_stmt = None
    if dry_run and pk_columns:
        pk_exists_stmt = build_pk_exists_statement(dest_table, pk_columns)

    if not common_columns:
        add_warning(warnings, table_name, "No shared columns found between SQLite and PostgreSQL.")
        summary.errors = summary.source_count
        return summary, inserted_pk_rows

    source_rows = sqlite_conn.execute(select(source_table)).mappings()
    for row in source_rows:
        payload = {column: row[column] for column in common_columns}

        if dry_run:
            if pk_exists_stmt:
                pk_payload = {f"pk_{column}": payload[column] for column in pk_columns}
                if pg_conn.execute(pk_exists_stmt, pk_payload).first():
                    summary.skipped += 1
                    continue
            if required_missing:
                summary.errors += 1
            else:
                summary.inserted += 1
            continue

        try:
            with pg_conn.begin_nested():
                result = pg_conn.execute(insert_stmt, payload)
            if result.rowcount == 0:
                summary.skipped += 1
            else:
                summary.inserted += result.rowcount
                if pk_columns:
                    inserted_pk_rows.append({column: payload[column] for column in pk_columns})
        except IntegrityError as exc:
            summary.errors += 1
            add_warning(warnings, table_name, f"Row integrity error: {exc.orig}")
        except SQLAlchemyError as exc:
            summary.errors += 1
            add_warning(warnings, table_name, f"Row SQLAlchemy error: {exc}")

    return summary, inserted_pk_rows


def apply_deferred_cycle_updates(
    table_name: str,
    sqlite_conn: Connection,
    pg_conn: Connection,
    inserted_pk_rows: list[dict[str, object]],
    deferred_columns: set[str],
    warnings: dict[str, list[str]],
) -> None:
    if not inserted_pk_rows or not deferred_columns:
        return

    _, source_table = load_table(sqlite_conn.engine, table_name)
    _, dest_table = load_table(pg_conn.engine, table_name)
    pk_columns = [column.name for column in dest_table.primary_key.columns]
    if not pk_columns:
        return

    inserted_pk_set = {
        tuple(pk_row[column] for column in pk_columns)
        for pk_row in inserted_pk_rows
    }

    update_stmt = dest_table.update().where(
        and_(*[dest_table.c[column] == bindparam(f"pk_{column}") for column in pk_columns])
    )

    updated_rows = 0
    error_rows = 0
    source_rows = sqlite_conn.execute(select(source_table)).mappings()
    for row in source_rows:
        pk_tuple = tuple(row[column] for column in pk_columns)
        if pk_tuple not in inserted_pk_set:
            continue

        update_values = {
            column: row[column]
            for column in deferred_columns
            if column in row and row[column] is not None
        }
        if not update_values:
            continue

        params = {f"pk_{column}": row[column] for column in pk_columns}
        params.update({f"value_{column}": value for column, value in update_values.items()})
        stmt = update_stmt.values({column: bindparam(f"value_{column}") for column in update_values})

        try:
            with pg_conn.begin_nested():
                result = pg_conn.execute(stmt, params)
            updated_rows += result.rowcount or 0
        except IntegrityError as exc:
            error_rows += 1
            add_warning(warnings, table_name, f"Deferred update integrity error: {exc.orig}")
        except SQLAlchemyError as exc:
            error_rows += 1
            add_warning(warnings, table_name, f"Deferred update SQLAlchemy error: {exc}")

    if updated_rows:
        add_warning(warnings, table_name, f"Deferred cycle update applied to {updated_rows} row(s).")
    if error_rows:
        add_warning(warnings, table_name, f"Deferred cycle update failed for {error_rows} row(s).")


def reset_sequence(pg_conn: Connection, table_name: str, id_column: str = "id") -> str | None:
    inspector = inspect(pg_conn)
    column_names = {column["name"] for column in inspector.get_columns(table_name)}
    if id_column not in column_names:
        return None

    preparer = IdentifierPreparer(pg_conn.dialect)
    qualified_table = quote_table_name(preparer, table_name)
    sequence_name = pg_conn.execute(
        text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
        {"table_name": qualified_table, "column_name": id_column},
    ).scalar_one_or_none()

    if not sequence_name:
        return None

    max_id = pg_conn.execute(
        text(f"SELECT COALESCE(MAX({preparer.quote(id_column)}), 0) FROM {qualified_table}")
    ).scalar_one()

    if max_id > 0:
        pg_conn.execute(text("SELECT setval(:sequence_name, :value, true)"), {"sequence_name": sequence_name, "value": max_id})
        return f"{sequence_name} => {max_id}"

    pg_conn.execute(text("SELECT setval(:sequence_name, 1, false)"), {"sequence_name": sequence_name})
    return f"{sequence_name} => 1 (empty table)"


def print_table_report(summary: TableSummary) -> None:
    print(
        f"{summary.table}: origen={summary.source_count}, "
        f"insertados={summary.inserted}, saltados={summary.skipped}, errores={summary.errors}"
    )


def print_final_report(
    ordered_tables: list[str],
    summaries: list[TableSummary],
    warnings: dict[str, list[str]],
    sequence_updates: list[str],
) -> None:
    print("\nResumen de migracion:")
    for summary in summaries:
        print_table_report(summary)

    print("\nOrden de migracion:")
    print(", ".join(ordered_tables) if ordered_tables else "(sin tablas)")

    if warnings:
        print("\nAvisos:")
        for message in warnings.get("_global", []):
            print(f"- global: {message}")
        for table in ordered_tables:
            for message in warnings.get(table, []):
                print(f"- {table}: {message}")

    if sequence_updates:
        print("\nSecuencias ajustadas:")
        for item in sequence_updates:
            print(f"- {item}")


def main() -> int:
    args = parse_args()

    sqlite_engine = create_engine(f"sqlite:///{args.sqlite_path}")
    pg_engine = create_engine(args.postgres_url)

    try:
        sqlite_tables = normalize_table_names(inspect(sqlite_engine).get_table_names())
        pg_tables = normalize_table_names(inspect(pg_engine).get_table_names())
    except SQLAlchemyError as exc:
        print(f"Error inspecting databases: {exc}", file=sys.stderr)
        return 1

    shared_tables = sorted(set(sqlite_tables) & set(pg_tables))
    sqlite_only = sorted(set(sqlite_tables) - set(pg_tables))
    pg_only = sorted(set(pg_tables) - set(sqlite_tables))

    if not shared_tables:
        print("No shared tables found between SQLite and PostgreSQL after exclusions.", file=sys.stderr)
        return 1

    ordered_tables, cyclic_tables, dependencies = build_dependency_order(pg_engine, shared_tables)
    warnings: dict[str, list[str]] = defaultdict(list)
    deferred_cycle_columns = detect_deferred_cycle_columns(pg_engine, cyclic_tables)

    if sqlite_only:
        add_warning(
            warnings,
            "_global",
            f"Tables only in SQLite and not migrated: {format_column_list(sqlite_only)}"
        )
    if pg_only:
        add_warning(
            warnings,
            "_global",
            f"Tables only in PostgreSQL and not read from source: {format_column_list(pg_only)}"
        )
    if cyclic_tables:
        add_warning(
            warnings,
            "_global",
            f"Dependency cycle detected. Remaining tables appended at the end: {format_column_list(cyclic_tables)}"
        )
    if deferred_cycle_columns:
        deferred_descriptions = [
            f"{table}({format_column_list(sorted(columns))})"
            for table, columns in sorted(deferred_cycle_columns.items())
        ]
        add_warning(
            warnings,
            "_global",
            f"Nullable cycle columns will be updated in a second pass: {format_column_list(deferred_descriptions)}"
        )

    print("Tablas compartidas:")
    print(", ".join(shared_tables))

    print("\nDependencias detectadas:")
    for table in ordered_tables:
        deps = sorted(dependencies.get(table, set()))
        print(f"- {table}: {format_column_list(deps)}")

    if warnings.get("_global"):
        print("\nAvisos globales:")
        for message in warnings["_global"]:
            print(f"- {message}")

    summaries: list[TableSummary] = []
    sequence_updates: list[str] = []
    inserted_pk_rows_by_table: dict[str, list[dict[str, object]]] = {}

    try:
        with sqlite_engine.connect() as sqlite_conn:
            with pg_engine.begin() as pg_conn:
                if args.truncate and not args.dry_run:
                    truncate_tables(pg_conn, list(reversed(ordered_tables)))

                for table in ordered_tables:
                    summary, inserted_pk_rows = migrate_table(
                        table_name=table,
                        sqlite_conn=sqlite_conn,
                        pg_conn=pg_conn,
                        dry_run=args.dry_run,
                        warnings=warnings,
                        deferred_columns=deferred_cycle_columns.get(table),
                    )
                    summaries.append(summary)
                    inserted_pk_rows_by_table[table] = inserted_pk_rows

                if not args.dry_run:
                    for table, deferred_columns in deferred_cycle_columns.items():
                        apply_deferred_cycle_updates(
                            table_name=table,
                            sqlite_conn=sqlite_conn,
                            pg_conn=pg_conn,
                            inserted_pk_rows=inserted_pk_rows_by_table.get(table, []),
                            deferred_columns=deferred_columns,
                            warnings=warnings,
                        )

                if not args.dry_run:
                    for table in ordered_tables:
                        sequence_update = reset_sequence(pg_conn, table)
                        if sequence_update:
                            sequence_updates.append(f"{table}: {sequence_update}")
    except SQLAlchemyError as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1

    print_final_report(ordered_tables, summaries, warnings, sequence_updates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
