"""make health ai analysis unique and track source

Revision ID: fb3c4d5e6f70
Revises: fa2b3c4d5e6f
Create Date: 2026-05-21 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "fb3c4d5e6f70"
down_revision = "fa2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("health_ai_analyses") as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

    op.execute(
        sa.text(
            """
            DELETE FROM health_ai_analyses
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM health_ai_analyses
                GROUP BY athlete_id, reference_date
            )
            """
        )
    )
    op.execute(sa.text("UPDATE health_ai_analyses SET source = 'legacy' WHERE source IS NULL OR source = ''"))
    op.execute(sa.text("UPDATE health_ai_analyses SET updated_at = created_at WHERE updated_at IS NULL"))

    with op.batch_alter_table("health_ai_analyses") as batch_op:
        batch_op.create_unique_constraint(
            "uq_health_ai_analyses_athlete_reference_date",
            ["athlete_id", "reference_date"],
        )


def downgrade() -> None:
    with op.batch_alter_table("health_ai_analyses") as batch_op:
        batch_op.drop_constraint("uq_health_ai_analyses_athlete_reference_date", type_="unique")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("source")
