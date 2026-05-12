"""add incline pct to planned session steps

Revision ID: ab7c8d9e0f1a
Revises: 9c21a43f5afe
Create Date: 2026-05-06 01:25:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ab7c8d9e0f1a"
down_revision = "9c21a43f5afe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("planned_session_steps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("incline_pct", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("planned_session_steps", schema=None) as batch_op:
        batch_op.drop_column("incline_pct")
