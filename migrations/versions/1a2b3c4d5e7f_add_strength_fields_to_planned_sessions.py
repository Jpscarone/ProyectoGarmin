"""add strength fields to planned sessions

Revision ID: 1a2b3c4d5e7f
Revises: f8b9c0d1e2f3
Create Date: 2026-05-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e7f"
down_revision = "f8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("planned_sessions", sa.Column("strength_focus", sa.String(length=50), nullable=True))
    op.add_column("planned_sessions", sa.Column("strength_rpe", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("planned_sessions", "strength_rpe")
    op.drop_column("planned_sessions", "strength_focus")
