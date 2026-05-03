"""add garmin accounts

Revision ID: f6a7b8c9d0e1
Revises: f5a6b7c8d9e0
Create Date: 2026-04-30 00:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "garmin_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("encrypted_password", sa.String(length=1024), nullable=True),
        sa.Column("token_dir", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("last_activity_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_garmin_accounts_athlete_id"), "garmin_accounts", ["athlete_id"], unique=False)
    op.create_index(op.f("ix_garmin_accounts_status"), "garmin_accounts", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_garmin_accounts_status"), table_name="garmin_accounts")
    op.drop_index(op.f("ix_garmin_accounts_athlete_id"), table_name="garmin_accounts")
    op.drop_table("garmin_accounts")
