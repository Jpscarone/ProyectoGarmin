"""alter garmin activity id to bigint

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-12 00:45:00.000000
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def _column_type_name(table_name: str, column_name: str) -> str | None:
    inspector = inspect(op.get_bind())
    for column in inspector.get_columns(table_name):
        if column["name"] == column_name:
            return str(column["type"]).lower()
    return None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    if context.is_offline_mode():
        if dialect == "postgresql":
            op.alter_column(
                "garmin_activities",
                "garmin_activity_id",
                existing_type=sa.Integer(),
                type_=sa.BigInteger(),
                existing_nullable=False,
                postgresql_using="garmin_activity_id::bigint",
            )
        return

    current_type = _column_type_name("garmin_activities", "garmin_activity_id")

    if current_type is None:
        return

    if "bigint" in current_type:
        return

    if dialect == "postgresql":
        op.alter_column(
            "garmin_activities",
            "garmin_activity_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
            postgresql_using="garmin_activity_id::bigint",
        )
        return

    if dialect == "sqlite":
        with op.batch_alter_table("garmin_activities", recreate="always") as batch_op:
            batch_op.alter_column(
                "garmin_activity_id",
                existing_type=sa.Integer(),
                type_=sa.BigInteger(),
                existing_nullable=False,
            )
        return

    op.alter_column(
        "garmin_activities",
        "garmin_activity_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name

    if context.is_offline_mode():
        if dialect == "postgresql":
            op.alter_column(
                "garmin_activities",
                "garmin_activity_id",
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
                existing_nullable=False,
                postgresql_using="garmin_activity_id::integer",
            )
        return

    current_type = _column_type_name("garmin_activities", "garmin_activity_id")

    if current_type is None or "int" not in current_type:
        return

    if "integer" in current_type and "big" not in current_type:
        return

    if dialect == "postgresql":
        op.alter_column(
            "garmin_activities",
            "garmin_activity_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
            postgresql_using="garmin_activity_id::integer",
        )
        return

    if dialect == "sqlite":
        with op.batch_alter_table("garmin_activities", recreate="always") as batch_op:
            batch_op.alter_column(
                "garmin_activity_id",
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
                existing_nullable=False,
            )
        return

    op.alter_column(
        "garmin_activities",
        "garmin_activity_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
