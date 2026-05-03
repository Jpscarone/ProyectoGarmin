"""add health ai analysis hash

Revision ID: f4a5b6c7d8e9
Revises: f3a4b5c6d7e8
Create Date: 2026-04-29 22:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f4a5b6c7d8e9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("health_ai_analyses", sa.Column("llm_json_hash", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_health_ai_analyses_llm_json_hash"), "health_ai_analyses", ["llm_json_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_health_ai_analyses_llm_json_hash"), table_name="health_ai_analyses")
    op.drop_column("health_ai_analyses", "llm_json_hash")
