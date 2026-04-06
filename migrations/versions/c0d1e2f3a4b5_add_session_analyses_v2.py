"""add session analyses v2

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-04-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("planned_session_id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("analysis_version", sa.String(length=50), server_default="v2", nullable=False),
        sa.Column("trigger_source", sa.String(length=100), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary_short", sa.Text(), nullable=True),
        sa.Column("analysis_natural", sa.Text(), nullable=True),
        sa.Column("coach_conclusion", sa.Text(), nullable=True),
        sa.Column("next_recommendation", sa.Text(), nullable=True),
        sa.Column("compliance_score", sa.Float(), nullable=True),
        sa.Column("execution_score", sa.Float(), nullable=True),
        sa.Column("control_score", sa.Float(), nullable=True),
        sa.Column("fatigue_score", sa.Float(), nullable=True),
        sa.Column("heat_impact_flag", sa.Boolean(), nullable=True),
        sa.Column("cardiac_drift_flag", sa.Boolean(), nullable=True),
        sa.Column("hydration_risk_flag", sa.Boolean(), nullable=True),
        sa.Column("pace_instability_flag", sa.Boolean(), nullable=True),
        sa.Column("manual_review_needed", sa.Boolean(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("llm_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["garmin_activities.id"]),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.ForeignKeyConstraint(["planned_session_id"], ["planned_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_session_analyses_athlete_id"), "session_analyses", ["athlete_id"], unique=False)
    op.create_index(op.f("ix_session_analyses_planned_session_id"), "session_analyses", ["planned_session_id"], unique=False)
    op.create_index(op.f("ix_session_analyses_activity_id"), "session_analyses", ["activity_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_session_analyses_activity_id"), table_name="session_analyses")
    op.drop_index(op.f("ix_session_analyses_planned_session_id"), table_name="session_analyses")
    op.drop_index(op.f("ix_session_analyses_athlete_id"), table_name="session_analyses")
    op.drop_table("session_analyses")
