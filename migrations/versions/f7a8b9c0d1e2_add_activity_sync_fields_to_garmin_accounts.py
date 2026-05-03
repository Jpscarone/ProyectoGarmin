"""add activity sync fields to garmin accounts

Revision ID: f7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-01 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d1e2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("garmin_accounts", sa.Column("last_activity_sync_status", sa.String(length=32), nullable=True))
    op.add_column("garmin_accounts", sa.Column("last_activity_sync_message", sa.Text(), nullable=True))
    op.add_column("garmin_accounts", sa.Column("last_activity_sync_start_date", sa.Date(), nullable=True))
    op.add_column("garmin_accounts", sa.Column("last_activity_sync_end_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("garmin_accounts", "last_activity_sync_end_date")
    op.drop_column("garmin_accounts", "last_activity_sync_start_date")
    op.drop_column("garmin_accounts", "last_activity_sync_message")
    op.drop_column("garmin_accounts", "last_activity_sync_status")
