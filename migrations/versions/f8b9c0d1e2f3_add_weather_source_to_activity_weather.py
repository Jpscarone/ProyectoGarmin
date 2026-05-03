"""add weather source to activity weather

Revision ID: f8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-05-01 13:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("activity_weather", sa.Column("weather_source", sa.String(length=50), nullable=True))
    op.add_column("activity_weather", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("activity_weather", sa.Column("condition_summary", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("activity_weather", "condition_summary")
    op.drop_column("activity_weather", "synced_at")
    op.drop_column("activity_weather", "weather_source")
