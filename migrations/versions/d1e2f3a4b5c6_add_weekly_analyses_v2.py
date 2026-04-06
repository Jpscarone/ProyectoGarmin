"""add weekly analyses v2

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-04-03 18:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("week_start_date", sa.Date(), nullable=False),
        sa.Column("week_end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("analysis_version", sa.String(length=50), server_default="v2", nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary_short", sa.Text(), nullable=True),
        sa.Column("analysis_natural", sa.Text(), nullable=True),
        sa.Column("coach_conclusion", sa.Text(), nullable=True),
        sa.Column("next_week_recommendation", sa.Text(), nullable=True),
        sa.Column("total_duration_sec", sa.Integer(), nullable=True),
        sa.Column("total_distance_m", sa.Float(), nullable=True),
        sa.Column("total_elevation_gain_m", sa.Float(), nullable=True),
        sa.Column("total_sessions", sa.Integer(), nullable=True),
        sa.Column("sessions_by_sport", sa.JSON(), nullable=True),
        sa.Column("time_in_zones", sa.JSON(), nullable=True),
        sa.Column("intensity_distribution", sa.JSON(), nullable=True),
        sa.Column("planned_sessions", sa.Integer(), nullable=True),
        sa.Column("completed_sessions", sa.Integer(), nullable=True),
        sa.Column("compliance_ratio", sa.Float(), nullable=True),
        sa.Column("load_score", sa.Float(), nullable=True),
        sa.Column("consistency_score", sa.Float(), nullable=True),
        sa.Column("fatigue_score", sa.Float(), nullable=True),
        sa.Column("balance_score", sa.Float(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("llm_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("athlete_id", "week_start_date", name="uq_weekly_analysis_athlete_week_start"),
    )
    op.create_index(op.f("ix_weekly_analyses_athlete_id"), "weekly_analyses", ["athlete_id"], unique=False)
    op.create_index(op.f("ix_weekly_analyses_week_start_date"), "weekly_analyses", ["week_start_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_weekly_analyses_week_start_date"), table_name="weekly_analyses")
    op.drop_index(op.f("ix_weekly_analyses_athlete_id"), table_name="weekly_analyses")
    op.drop_table("weekly_analyses")
