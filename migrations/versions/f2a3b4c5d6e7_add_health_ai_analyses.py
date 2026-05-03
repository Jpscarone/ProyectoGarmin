"""add health ai analyses

Revision ID: f2a3b4c5d6e7
Revises: e2f3a4b5c6d7
Create Date: 2026-04-23 22:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f2a3b4c5d6e7"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "health_ai_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("llm_json", sa.JSON(), nullable=True),
        sa.Column("ai_response_json", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("training_recommendation", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_health_ai_analyses_athlete_id"), "health_ai_analyses", ["athlete_id"], unique=False)
    op.create_index(op.f("ix_health_ai_analyses_reference_date"), "health_ai_analyses", ["reference_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_health_ai_analyses_reference_date"), table_name="health_ai_analyses")
    op.drop_index(op.f("ix_health_ai_analyses_athlete_id"), table_name="health_ai_analyses")
    op.drop_table("health_ai_analyses")
