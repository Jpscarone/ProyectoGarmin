"""Create athletes table.

Revision ID: 0002_create_athletes_table
Revises: 0001_initial_setup
Create Date: 2026-03-15 17:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_create_athletes_table"
down_revision = "0001_initial_setup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "athletes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.Column("resting_hr", sa.Integer(), nullable=True),
        sa.Column("lactate_threshold_hr", sa.Integer(), nullable=True),
        sa.Column("running_threshold_pace_sec_km", sa.Integer(), nullable=True),
        sa.Column("cycling_ftp", sa.Integer(), nullable=True),
        sa.Column("vo2max", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_athletes_id"), "athletes", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_athletes_id"), table_name="athletes")
    op.drop_table("athletes")
