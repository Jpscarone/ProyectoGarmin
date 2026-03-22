"""add athlete zone sources

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-03-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("athletes", sa.Column("source_hr_zones", sa.String(length=50), nullable=True))
    op.add_column("athletes", sa.Column("source_power_zones", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("athletes", "source_power_zones")
    op.drop_column("athletes", "source_hr_zones")
