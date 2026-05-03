"""extend daily health metrics for readiness

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-23 12:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("daily_health_metrics", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sleep_duration_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("body_battery_morning", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("body_battery_max", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("hrv_value", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("training_load", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source", sa.String(length=50), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE daily_health_metrics
            SET
                sleep_duration_minutes = CASE
                    WHEN sleep_hours IS NOT NULL THEN CAST(ROUND(sleep_hours * 60.0) AS INTEGER)
                    ELSE NULL
                END,
                body_battery_morning = body_battery_start,
                body_battery_max = CASE
                    WHEN body_battery_start IS NULL AND body_battery_end IS NULL AND body_battery_min IS NULL THEN NULL
                    ELSE max(
                        COALESCE(body_battery_start, 0),
                        COALESCE(body_battery_end, 0),
                        COALESCE(body_battery_min, 0)
                    )
                END,
                hrv_value = hrv_avg_ms,
                source = COALESCE(source, 'garmin')
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("daily_health_metrics", schema=None) as batch_op:
        batch_op.drop_column("source")
        batch_op.drop_column("notes")
        batch_op.drop_column("training_load")
        batch_op.drop_column("hrv_value")
        batch_op.drop_column("body_battery_max")
        batch_op.drop_column("body_battery_morning")
        batch_op.drop_column("sleep_duration_minutes")
