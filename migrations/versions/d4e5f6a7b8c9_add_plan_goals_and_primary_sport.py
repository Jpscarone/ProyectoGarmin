"""add plan goals and primary sport

Revision ID: d4e5f6a7b8c9
Revises: b3c4d5e6f7a8
Create Date: 2026-03-22
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "d4e5f6a7b8c9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _foreign_key_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys(table_name)
        if foreign_key.get("name")
    }


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if context.is_offline_mode():
        op.add_column("training_plans", sa.Column("sport_type", sa.String(length=100), nullable=True))
        op.add_column("goals", sa.Column("training_plan_id", sa.Integer(), nullable=True))
        op.add_column("goals", sa.Column("goal_role", sa.String(length=20), nullable=True))
        op.create_index(op.f("ix_goals_training_plan_id"), "goals", ["training_plan_id"], unique=False)
        op.create_foreign_key(
            "fk_goals_training_plan_id_training_plans",
            "goals",
            "training_plans",
            ["training_plan_id"],
            ["id"],
        )
        op.execute(
            """
            UPDATE goals
            SET training_plan_id = (
                SELECT training_plans.id
                FROM training_plans
                WHERE training_plans.goal_id = goals.id
                LIMIT 1
            )
            WHERE id IN (SELECT goal_id FROM training_plans WHERE goal_id IS NOT NULL)
            """
        )
        op.execute(
            """
            UPDATE goals
            SET goal_role = 'primary'
            WHERE id IN (SELECT goal_id FROM training_plans WHERE goal_id IS NOT NULL)
            """
        )
        op.execute(
            """
            UPDATE training_plans
            SET sport_type = (
                SELECT goals.sport_type
                FROM goals
                WHERE goals.id = training_plans.goal_id
                LIMIT 1
            )
            WHERE goal_id IS NOT NULL
            """
        )
        return

    training_plan_columns = _column_names("training_plans")
    if "sport_type" not in training_plan_columns:
        op.add_column("training_plans", sa.Column("sport_type", sa.String(length=100), nullable=True))

    goal_columns = _column_names("goals")
    goal_foreign_keys = _foreign_key_names("goals")
    goal_indexes = _index_names("goals")

    needs_goal_batch = (
        "training_plan_id" not in goal_columns
        or "goal_role" not in goal_columns
        or "ix_goals_training_plan_id" not in goal_indexes
        or "fk_goals_training_plan_id_training_plans" not in goal_foreign_keys
    )

    if needs_goal_batch:
        if _is_sqlite():
            with op.batch_alter_table("goals", recreate="always") as batch_op:
                if "training_plan_id" not in goal_columns:
                    batch_op.add_column(sa.Column("training_plan_id", sa.Integer(), nullable=True))
                if "goal_role" not in goal_columns:
                    batch_op.add_column(sa.Column("goal_role", sa.String(length=20), nullable=True))
                if "ix_goals_training_plan_id" not in goal_indexes:
                    batch_op.create_index(batch_op.f("ix_goals_training_plan_id"), ["training_plan_id"], unique=False)
                if "fk_goals_training_plan_id_training_plans" not in goal_foreign_keys:
                    batch_op.create_foreign_key(
                        "fk_goals_training_plan_id_training_plans",
                        "training_plans",
                        ["training_plan_id"],
                        ["id"],
                    )
        else:
            if "training_plan_id" not in goal_columns:
                op.add_column("goals", sa.Column("training_plan_id", sa.Integer(), nullable=True))
            if "goal_role" not in goal_columns:
                op.add_column("goals", sa.Column("goal_role", sa.String(length=20), nullable=True))
            if "ix_goals_training_plan_id" not in goal_indexes:
                op.create_index(op.f("ix_goals_training_plan_id"), "goals", ["training_plan_id"], unique=False)
            if "fk_goals_training_plan_id_training_plans" not in goal_foreign_keys:
                op.create_foreign_key(
                    "fk_goals_training_plan_id_training_plans",
                    "goals",
                    "training_plans",
                    ["training_plan_id"],
                    ["id"],
                )

    op.execute(
        """
        UPDATE goals
        SET training_plan_id = (
            SELECT training_plans.id
            FROM training_plans
            WHERE training_plans.goal_id = goals.id
            LIMIT 1
        )
        WHERE id IN (SELECT goal_id FROM training_plans WHERE goal_id IS NOT NULL)
        """
    )
    op.execute(
        """
        UPDATE goals
        SET goal_role = 'primary'
        WHERE id IN (SELECT goal_id FROM training_plans WHERE goal_id IS NOT NULL)
        """
    )
    op.execute(
        """
        UPDATE training_plans
        SET sport_type = (
            SELECT goals.sport_type
            FROM goals
            WHERE goals.id = training_plans.goal_id
            LIMIT 1
        )
        WHERE goal_id IS NOT NULL
        """
    )


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_constraint("fk_goals_training_plan_id_training_plans", "goals", type_="foreignkey")
        op.drop_index(op.f("ix_goals_training_plan_id"), table_name="goals")
        op.drop_column("goals", "goal_role")
        op.drop_column("goals", "training_plan_id")
        op.drop_column("training_plans", "sport_type")
        return

    goal_columns = _column_names("goals")
    goal_foreign_keys = _foreign_key_names("goals")
    goal_indexes = _index_names("goals")

    needs_goal_batch = (
        "training_plan_id" in goal_columns
        or "goal_role" in goal_columns
        or "ix_goals_training_plan_id" in goal_indexes
        or "fk_goals_training_plan_id_training_plans" in goal_foreign_keys
    )

    if needs_goal_batch:
        if _is_sqlite():
            with op.batch_alter_table("goals", recreate="always") as batch_op:
                if "fk_goals_training_plan_id_training_plans" in goal_foreign_keys:
                    batch_op.drop_constraint("fk_goals_training_plan_id_training_plans", type_="foreignkey")
                if "ix_goals_training_plan_id" in goal_indexes:
                    batch_op.drop_index(batch_op.f("ix_goals_training_plan_id"))
                if "goal_role" in goal_columns:
                    batch_op.drop_column("goal_role")
                if "training_plan_id" in goal_columns:
                    batch_op.drop_column("training_plan_id")
        else:
            if "fk_goals_training_plan_id_training_plans" in goal_foreign_keys:
                op.drop_constraint("fk_goals_training_plan_id_training_plans", "goals", type_="foreignkey")
            if "ix_goals_training_plan_id" in goal_indexes:
                op.drop_index(op.f("ix_goals_training_plan_id"), table_name="goals")
            if "goal_role" in goal_columns:
                op.drop_column("goals", "goal_role")
            if "training_plan_id" in goal_columns:
                op.drop_column("goals", "training_plan_id")

    training_plan_columns = _column_names("training_plans")
    if "sport_type" in training_plan_columns:
        op.drop_column("training_plans", "sport_type")
