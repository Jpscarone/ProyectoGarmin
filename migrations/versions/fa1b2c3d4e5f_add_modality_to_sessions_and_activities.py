"""add modality to sessions and activities

Revision ID: fa1b2c3d4e5f
Revises: f8b9c0d1e2f3
Create Date: 2026-05-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "fa1b2c3d4e5f"
down_revision = "f8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("planned_sessions", sa.Column("modality", sa.String(length=20), nullable=True))
    op.add_column("garmin_activities", sa.Column("modality", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("garmin_activities", "modality")
    op.drop_column("planned_sessions", "modality")
