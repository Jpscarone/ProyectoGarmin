"""add athlete garmin profile snapshot

Revision ID: f1a2b3c4d5e6
Revises: e6f7a8b9c0d1
Create Date: 2026-03-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("athletes", sa.Column("hr_zones_json", sa.Text(), nullable=True))
    op.add_column("athletes", sa.Column("power_zones_json", sa.Text(), nullable=True))
    op.add_column("athletes", sa.Column("garmin_profile_snapshot_json", sa.Text(), nullable=True))
    op.add_column("athletes", sa.Column("garmin_profile_last_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("athletes", "garmin_profile_last_synced_at")
    op.drop_column("athletes", "garmin_profile_snapshot_json")
    op.drop_column("athletes", "power_zones_json")
    op.drop_column("athletes", "hr_zones_json")
