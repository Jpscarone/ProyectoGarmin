"""add activity weather

Revision ID: 2d4f5b6c7d8e
Revises: 7f3f1f1f1a1c
Create Date: 2026-03-15 22:55:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2d4f5b6c7d8e"
down_revision = "7f3f1f1f1a1c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_weather",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("garmin_activity_id", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("temperature_start_c", sa.Float(), nullable=True),
        sa.Column("apparent_temperature_start_c", sa.Float(), nullable=True),
        sa.Column("humidity_start_pct", sa.Float(), nullable=True),
        sa.Column("dew_point_start_c", sa.Float(), nullable=True),
        sa.Column("wind_speed_start_kmh", sa.Float(), nullable=True),
        sa.Column("wind_direction_start_deg", sa.Float(), nullable=True),
        sa.Column("pressure_start_hpa", sa.Float(), nullable=True),
        sa.Column("precipitation_start_mm", sa.Float(), nullable=True),
        sa.Column("temperature_min_c", sa.Float(), nullable=True),
        sa.Column("temperature_max_c", sa.Float(), nullable=True),
        sa.Column("wind_speed_avg_kmh", sa.Float(), nullable=True),
        sa.Column("precipitation_total_mm", sa.Float(), nullable=True),
        sa.Column("raw_weather_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["garmin_activity_id"], ["garmin_activities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("garmin_activity_id", name="uq_activity_weather_activity"),
    )
    with op.batch_alter_table("activity_weather", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_activity_weather_garmin_activity_id"), ["garmin_activity_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("activity_weather", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_activity_weather_garmin_activity_id"))

    op.drop_table("activity_weather")
