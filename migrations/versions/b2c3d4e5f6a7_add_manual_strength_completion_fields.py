"""add manual strength completion fields

Revision ID: b2c3d4e5f6a7
Revises: ab7c8d9e0f1a
Create Date: 2026-05-10 15:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "ab7c8d9e0f1a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("planned_sessions", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("planned_sessions", sa.Column("completion_source", sa.String(length=20), nullable=True))
    op.add_column("planned_sessions", sa.Column("manual_duration_sec", sa.Integer(), nullable=True))
    op.add_column("planned_sessions", sa.Column("manual_strength_rpe", sa.Integer(), nullable=True))
    op.add_column("planned_sessions", sa.Column("manual_strength_focus", sa.String(length=50), nullable=True))
    op.add_column("planned_sessions", sa.Column("manual_completion_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("planned_sessions", "manual_completion_notes")
    op.drop_column("planned_sessions", "manual_strength_focus")
    op.drop_column("planned_sessions", "manual_strength_rpe")
    op.drop_column("planned_sessions", "manual_duration_sec")
    op.drop_column("planned_sessions", "completion_source")
    op.drop_column("planned_sessions", "completed_at")
