"""add analysis reports

Revision ID: 8b9c0d1e2f3a
Revises: 6a7b8c9d0e1f
Create Date: 2026-03-16 00:20:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8b9c0d1e2f3a"
down_revision = "6a7b8c9d0e1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("training_day_id", sa.Integer(), nullable=True),
        sa.Column("session_group_id", sa.Integer(), nullable=True),
        sa.Column("planned_session_id", sa.Integer(), nullable=True),
        sa.Column("garmin_activity_id_fk", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("overall_status", sa.String(length=50), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("recommendation_text", sa.Text(), nullable=True),
        sa.Column("analysis_context_json", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.ForeignKeyConstraint(["garmin_activity_id_fk"], ["garmin_activities.id"]),
        sa.ForeignKeyConstraint(["planned_session_id"], ["planned_sessions.id"]),
        sa.ForeignKeyConstraint(["session_group_id"], ["session_groups.id"]),
        sa.ForeignKeyConstraint(["training_day_id"], ["training_days.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("analysis_reports", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_analysis_reports_athlete_id"), ["athlete_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_analysis_reports_training_day_id"), ["training_day_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_analysis_reports_session_group_id"), ["session_group_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_analysis_reports_planned_session_id"), ["planned_session_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_analysis_reports_garmin_activity_id_fk"), ["garmin_activity_id_fk"], unique=False)

    op.create_table(
        "analysis_report_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_report_id", sa.Integer(), nullable=False),
        sa.Column("item_order", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=50), nullable=False),
        sa.Column("reference_label", sa.String(length=255), nullable=True),
        sa.Column("planned_value_text", sa.Text(), nullable=True),
        sa.Column("actual_value_text", sa.Text(), nullable=True),
        sa.Column("item_score", sa.Float(), nullable=True),
        sa.Column("item_status", sa.String(length=50), nullable=False),
        sa.Column("comment_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_report_id"], ["analysis_reports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("analysis_report_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_analysis_report_items_analysis_report_id"), ["analysis_report_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("analysis_report_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_analysis_report_items_analysis_report_id"))
    op.drop_table("analysis_report_items")

    with op.batch_alter_table("analysis_reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_analysis_reports_garmin_activity_id_fk"))
        batch_op.drop_index(batch_op.f("ix_analysis_reports_planned_session_id"))
        batch_op.drop_index(batch_op.f("ix_analysis_reports_session_group_id"))
        batch_op.drop_index(batch_op.f("ix_analysis_reports_training_day_id"))
        batch_op.drop_index(batch_op.f("ix_analysis_reports_athlete_id"))
    op.drop_table("analysis_reports")
