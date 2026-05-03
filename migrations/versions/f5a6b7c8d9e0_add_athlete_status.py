"""add athlete status

Revision ID: f5a6b7c8d9e0
Revises: f4a5b6c7d8e9
Create Date: 2026-04-29 23:50:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f5a6b7c8d9e0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "athletes",
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
    )
    op.create_index(op.f("ix_athletes_status"), "athletes", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_athletes_status"), table_name="athletes")
    op.drop_column("athletes", "status")
