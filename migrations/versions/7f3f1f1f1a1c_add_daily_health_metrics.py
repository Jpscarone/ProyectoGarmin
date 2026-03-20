"""add daily health metrics

Revision ID: 7f3f1f1f1a1c
Revises: 9c4b2dd09d25
Create Date: 2026-03-15 22:05:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7f3f1f1f1a1c"
down_revision = "9c4b2dd09d25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_health_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("sleep_hours", sa.Float(), nullable=True),
        sa.Column("sleep_score", sa.Integer(), nullable=True),
        sa.Column("deep_sleep_min", sa.Integer(), nullable=True),
        sa.Column("rem_sleep_min", sa.Integer(), nullable=True),
        sa.Column("awake_count", sa.Integer(), nullable=True),
        sa.Column("stress_avg", sa.Integer(), nullable=True),
        sa.Column("stress_max", sa.Integer(), nullable=True),
        sa.Column("high_stress_duration_min", sa.Integer(), nullable=True),
        sa.Column("body_battery_start", sa.Integer(), nullable=True),
        sa.Column("body_battery_min", sa.Integer(), nullable=True),
        sa.Column("body_battery_end", sa.Integer(), nullable=True),
        sa.Column("hrv_status", sa.String(length=100), nullable=True),
        sa.Column("hrv_avg_ms", sa.Float(), nullable=True),
        sa.Column("resting_hr", sa.Integer(), nullable=True),
        sa.Column("avg_daily_hr", sa.Integer(), nullable=True),
        sa.Column("recovery_time_hours", sa.Float(), nullable=True),
        sa.Column("vo2max", sa.Float(), nullable=True),
        sa.Column("spo2_avg", sa.Float(), nullable=True),
        sa.Column("respiration_avg", sa.Float(), nullable=True),
        sa.Column("raw_health_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("athlete_id", "metric_date", name="uq_daily_health_metric_athlete_date"),
    )
    with op.batch_alter_table("daily_health_metrics", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_daily_health_metrics_athlete_id"), ["athlete_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("daily_health_metrics", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_daily_health_metrics_athlete_id"))

    op.drop_table("daily_health_metrics")
