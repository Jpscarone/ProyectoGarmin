"""add health sync states

Revision ID: f3a4b5c6d7e8
Revises: f2a3b4c5d6e7
Create Date: 2026-04-29 22:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f3a4b5c6d7e8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "health_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), server_default="garmin", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_for_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="idle", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("records_created", sa.Integer(), nullable=True),
        sa.Column("records_updated", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("athlete_id", "source", name="uq_health_sync_states_athlete_source"),
    )
    op.create_index(op.f("ix_health_sync_states_athlete_id"), "health_sync_states", ["athlete_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_health_sync_states_athlete_id"), table_name="health_sync_states")
    op.drop_table("health_sync_states")
