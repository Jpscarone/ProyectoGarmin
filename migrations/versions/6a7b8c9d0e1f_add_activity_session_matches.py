"""add activity session matches

Revision ID: 6a7b8c9d0e1f
Revises: 2d4f5b6c7d8e
Create Date: 2026-03-15 23:35:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6a7b8c9d0e1f"
down_revision = "2d4f5b6c7d8e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_session_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("garmin_activity_id_fk", sa.Integer(), nullable=False),
        sa.Column("planned_session_id_fk", sa.Integer(), nullable=False),
        sa.Column("training_day_id_fk", sa.Integer(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.Column("match_method", sa.String(length=50), nullable=False),
        sa.Column("match_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.ForeignKeyConstraint(["garmin_activity_id_fk"], ["garmin_activities.id"]),
        sa.ForeignKeyConstraint(["planned_session_id_fk"], ["planned_sessions.id"]),
        sa.ForeignKeyConstraint(["training_day_id_fk"], ["training_days.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("garmin_activity_id_fk", name="uq_activity_session_match_activity"),
        sa.UniqueConstraint("planned_session_id_fk", name="uq_activity_session_match_planned_session"),
    )
    with op.batch_alter_table("activity_session_matches", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_activity_session_matches_athlete_id"), ["athlete_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_activity_session_matches_garmin_activity_id_fk"), ["garmin_activity_id_fk"], unique=False)
        batch_op.create_index(batch_op.f("ix_activity_session_matches_planned_session_id_fk"), ["planned_session_id_fk"], unique=False)
        batch_op.create_index(batch_op.f("ix_activity_session_matches_training_day_id_fk"), ["training_day_id_fk"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("activity_session_matches", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_activity_session_matches_training_day_id_fk"))
        batch_op.drop_index(batch_op.f("ix_activity_session_matches_planned_session_id_fk"))
        batch_op.drop_index(batch_op.f("ix_activity_session_matches_garmin_activity_id_fk"))
        batch_op.drop_index(batch_op.f("ix_activity_session_matches_athlete_id"))

    op.drop_table("activity_session_matches")
