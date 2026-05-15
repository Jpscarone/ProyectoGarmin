"""add pending items timezone and job counters

Revision ID: e8f9a0b1c2d3
Revises: e7f8a9b0c1d2
Create Date: 2026-05-14 00:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("athletes", sa.Column("timezone", sa.String(length=64), nullable=True))

    op.add_column("scheduled_sync_job_logs", sa.Column("pending_items_created", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scheduled_sync_job_logs", sa.Column("pending_items_resolved", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "pending_training_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("reference_date", sa.Date(), nullable=True),
        sa.Column("garmin_activity_id", sa.Integer(), nullable=True),
        sa.Column("planned_session_id", sa.Integer(), nullable=True),
        sa.Column("analysis_report_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("resolution_hint", sa.Text(), nullable=True),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_report_id"], ["analysis_reports.id"]),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.ForeignKeyConstraint(["garmin_activity_id"], ["garmin_activities.id"]),
        sa.ForeignKeyConstraint(["planned_session_id"], ["planned_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pending_training_items_athlete_id"), "pending_training_items", ["athlete_id"], unique=False)
    op.create_index(op.f("ix_pending_training_items_item_type"), "pending_training_items", ["item_type"], unique=False)
    op.create_index(op.f("ix_pending_training_items_status"), "pending_training_items", ["status"], unique=False)
    op.create_index(op.f("ix_pending_training_items_reference_date"), "pending_training_items", ["reference_date"], unique=False)
    op.create_index(op.f("ix_pending_training_items_garmin_activity_id"), "pending_training_items", ["garmin_activity_id"], unique=False)
    op.create_index(op.f("ix_pending_training_items_planned_session_id"), "pending_training_items", ["planned_session_id"], unique=False)
    op.create_index(op.f("ix_pending_training_items_analysis_report_id"), "pending_training_items", ["analysis_report_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pending_training_items_analysis_report_id"), table_name="pending_training_items")
    op.drop_index(op.f("ix_pending_training_items_planned_session_id"), table_name="pending_training_items")
    op.drop_index(op.f("ix_pending_training_items_garmin_activity_id"), table_name="pending_training_items")
    op.drop_index(op.f("ix_pending_training_items_reference_date"), table_name="pending_training_items")
    op.drop_index(op.f("ix_pending_training_items_status"), table_name="pending_training_items")
    op.drop_index(op.f("ix_pending_training_items_item_type"), table_name="pending_training_items")
    op.drop_index(op.f("ix_pending_training_items_athlete_id"), table_name="pending_training_items")
    op.drop_table("pending_training_items")
    op.drop_column("scheduled_sync_job_logs", "pending_items_resolved")
    op.drop_column("scheduled_sync_job_logs", "pending_items_created")
    op.drop_column("athletes", "timezone")
