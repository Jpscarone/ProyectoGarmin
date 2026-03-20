"""add final conclusion to analysis reports

Revision ID: b3c4d5e6f7a8
Revises: 8b9c0d1e2f3a
Create Date: 2026-03-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b3c4d5e6f7a8"
down_revision = "8b9c0d1e2f3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_reports", sa.Column("final_conclusion_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_reports", "final_conclusion_text")
