"""add session templates

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-03-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("sport_type", sa.String(length=100), nullable=True),
        sa.Column("discipline_variant", sa.String(length=100), nullable=True),
        sa.Column("session_type", sa.String(length=100), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("expected_duration_min", sa.Integer(), nullable=True),
        sa.Column("expected_distance_km", sa.Float(), nullable=True),
        sa.Column("expected_elevation_gain_m", sa.Float(), nullable=True),
        sa.Column("target_hr_zone", sa.String(length=50), nullable=True),
        sa.Column("target_power_zone", sa.String(length=50), nullable=True),
        sa.Column("target_notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_session_templates_sport_type"), "session_templates", ["sport_type"], unique=False)
    op.create_index(op.f("ix_session_templates_session_type"), "session_templates", ["session_type"], unique=False)

    op.create_table(
        "session_template_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_template_id", sa.Integer(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=50), nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.Column("target_hr_min", sa.Integer(), nullable=True),
        sa.Column("target_hr_max", sa.Integer(), nullable=True),
        sa.Column("target_power_min", sa.Integer(), nullable=True),
        sa.Column("target_power_max", sa.Integer(), nullable=True),
        sa.Column("target_pace_min_sec_km", sa.Integer(), nullable=True),
        sa.Column("target_pace_max_sec_km", sa.Integer(), nullable=True),
        sa.Column("target_cadence_min", sa.Integer(), nullable=True),
        sa.Column("target_cadence_max", sa.Integer(), nullable=True),
        sa.Column("target_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_template_id"], ["session_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_session_template_steps_session_template_id"),
        "session_template_steps",
        ["session_template_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_session_template_steps_session_template_id"), table_name="session_template_steps")
    op.drop_table("session_template_steps")
    op.drop_index(op.f("ix_session_templates_session_type"), table_name="session_templates")
    op.drop_index(op.f("ix_session_templates_sport_type"), table_name="session_templates")
    op.drop_table("session_templates")
