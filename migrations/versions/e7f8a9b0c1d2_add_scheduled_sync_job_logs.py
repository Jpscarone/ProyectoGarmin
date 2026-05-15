"""add scheduled sync job logs

Revision ID: e7f8a9b0c1d2
Revises: c3d4e5f6a7b8
Create Date: 2026-05-14 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_sync_job_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=True),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("activities_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activities_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activities_linked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activity_analyses_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("health_days_synced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("health_ai_analyses_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weekly_analyses_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scheduled_sync_job_logs_athlete_id"), "scheduled_sync_job_logs", ["athlete_id"], unique=False)
    op.create_index(op.f("ix_scheduled_sync_job_logs_job_type"), "scheduled_sync_job_logs", ["job_type"], unique=False)
    op.create_index(op.f("ix_scheduled_sync_job_logs_started_at"), "scheduled_sync_job_logs", ["started_at"], unique=False)
    op.create_index(op.f("ix_scheduled_sync_job_logs_status"), "scheduled_sync_job_logs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scheduled_sync_job_logs_status"), table_name="scheduled_sync_job_logs")
    op.drop_index(op.f("ix_scheduled_sync_job_logs_started_at"), table_name="scheduled_sync_job_logs")
    op.drop_index(op.f("ix_scheduled_sync_job_logs_job_type"), table_name="scheduled_sync_job_logs")
    op.drop_index(op.f("ix_scheduled_sync_job_logs_athlete_id"), table_name="scheduled_sync_job_logs")
    op.drop_table("scheduled_sync_job_logs")
