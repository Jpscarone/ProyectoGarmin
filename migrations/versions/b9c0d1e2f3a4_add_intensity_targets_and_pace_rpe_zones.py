"""add intensity targets and pace/rpe zones

Revision ID: b9c0d1e2f3a4
Revises: a1b2c3d4e5f6
Create Date: 2026-03-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b9c0d1e2f3a4"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("athletes", sa.Column("pace_zones_json", sa.Text(), nullable=True))
    op.add_column("athletes", sa.Column("rpe_zones_json", sa.Text(), nullable=True))
    op.add_column("athletes", sa.Column("source_pace_zones", sa.String(length=50), nullable=True))
    op.add_column("athletes", sa.Column("source_rpe_zones", sa.String(length=50), nullable=True))

    op.add_column("planned_sessions", sa.Column("target_type", sa.String(length=20), nullable=True))
    op.add_column("planned_sessions", sa.Column("target_pace_zone", sa.String(length=50), nullable=True))
    op.add_column("planned_sessions", sa.Column("target_rpe_zone", sa.String(length=50), nullable=True))

    op.add_column("planned_session_steps", sa.Column("target_type", sa.String(length=20), nullable=True))
    op.add_column("planned_session_steps", sa.Column("target_hr_zone", sa.String(length=50), nullable=True))
    op.add_column("planned_session_steps", sa.Column("target_power_zone", sa.String(length=50), nullable=True))
    op.add_column("planned_session_steps", sa.Column("target_pace_zone", sa.String(length=50), nullable=True))
    op.add_column("planned_session_steps", sa.Column("target_rpe_zone", sa.String(length=50), nullable=True))

    op.add_column("session_templates", sa.Column("target_type", sa.String(length=20), nullable=True))
    op.add_column("session_templates", sa.Column("target_pace_zone", sa.String(length=50), nullable=True))
    op.add_column("session_templates", sa.Column("target_rpe_zone", sa.String(length=50), nullable=True))

    op.add_column("session_template_steps", sa.Column("target_type", sa.String(length=20), nullable=True))
    op.add_column("session_template_steps", sa.Column("target_hr_zone", sa.String(length=50), nullable=True))
    op.add_column("session_template_steps", sa.Column("target_power_zone", sa.String(length=50), nullable=True))
    op.add_column("session_template_steps", sa.Column("target_pace_zone", sa.String(length=50), nullable=True))
    op.add_column("session_template_steps", sa.Column("target_rpe_zone", sa.String(length=50), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("UPDATE planned_sessions SET target_type = 'power' WHERE target_type IS NULL AND target_power_zone IS NOT NULL"))
    conn.execute(sa.text("UPDATE planned_sessions SET target_type = 'hr' WHERE target_type IS NULL AND target_hr_zone IS NOT NULL"))

    conn.execute(sa.text("UPDATE planned_session_steps SET target_type = 'power' WHERE target_type IS NULL AND (target_power_min IS NOT NULL OR target_power_max IS NOT NULL)"))
    conn.execute(sa.text("UPDATE planned_session_steps SET target_type = 'pace' WHERE target_type IS NULL AND (target_pace_min_sec_km IS NOT NULL OR target_pace_max_sec_km IS NOT NULL)"))
    conn.execute(sa.text("UPDATE planned_session_steps SET target_type = 'hr' WHERE target_type IS NULL AND (target_hr_min IS NOT NULL OR target_hr_max IS NOT NULL)"))

    conn.execute(sa.text("UPDATE session_templates SET target_type = 'power' WHERE target_type IS NULL AND target_power_zone IS NOT NULL"))
    conn.execute(sa.text("UPDATE session_templates SET target_type = 'hr' WHERE target_type IS NULL AND target_hr_zone IS NOT NULL"))

    conn.execute(sa.text("UPDATE session_template_steps SET target_type = 'power' WHERE target_type IS NULL AND (target_power_min IS NOT NULL OR target_power_max IS NOT NULL)"))
    conn.execute(sa.text("UPDATE session_template_steps SET target_type = 'pace' WHERE target_type IS NULL AND (target_pace_min_sec_km IS NOT NULL OR target_pace_max_sec_km IS NOT NULL)"))
    conn.execute(sa.text("UPDATE session_template_steps SET target_type = 'hr' WHERE target_type IS NULL AND (target_hr_min IS NOT NULL OR target_hr_max IS NOT NULL)"))


def downgrade() -> None:
    op.drop_column("session_template_steps", "target_rpe_zone")
    op.drop_column("session_template_steps", "target_pace_zone")
    op.drop_column("session_template_steps", "target_power_zone")
    op.drop_column("session_template_steps", "target_hr_zone")
    op.drop_column("session_template_steps", "target_type")

    op.drop_column("session_templates", "target_rpe_zone")
    op.drop_column("session_templates", "target_pace_zone")
    op.drop_column("session_templates", "target_type")

    op.drop_column("planned_session_steps", "target_rpe_zone")
    op.drop_column("planned_session_steps", "target_pace_zone")
    op.drop_column("planned_session_steps", "target_power_zone")
    op.drop_column("planned_session_steps", "target_hr_zone")
    op.drop_column("planned_session_steps", "target_type")

    op.drop_column("planned_sessions", "target_rpe_zone")
    op.drop_column("planned_sessions", "target_pace_zone")
    op.drop_column("planned_sessions", "target_type")

    op.drop_column("athletes", "source_rpe_zones")
    op.drop_column("athletes", "source_pace_zones")
    op.drop_column("athletes", "rpe_zones_json")
    op.drop_column("athletes", "pace_zones_json")
