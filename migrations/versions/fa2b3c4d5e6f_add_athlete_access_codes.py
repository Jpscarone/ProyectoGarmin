"""add athlete access codes

Revision ID: fa2b3c4d5e6f
Revises: f9a0b1c2d3e4
Create Date: 2026-05-18 12:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "fa2b3c4d5e6f"
down_revision: str | Sequence[str] | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "athlete_access_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("access_code", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_athlete_access_codes_athlete_id"), "athlete_access_codes", ["athlete_id"], unique=False)
    op.create_index(op.f("ix_athlete_access_codes_access_code"), "athlete_access_codes", ["access_code"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_athlete_access_codes_access_code"), table_name="athlete_access_codes")
    op.drop_index(op.f("ix_athlete_access_codes_athlete_id"), table_name="athlete_access_codes")
    op.drop_table("athlete_access_codes")
