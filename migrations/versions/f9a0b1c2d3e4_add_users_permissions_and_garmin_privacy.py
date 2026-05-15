"""add users permissions and garmin privacy

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-05-14 23:40:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f9a0b1c2d3e4"
down_revision: str | Sequence[str] | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.create_table(
        "user_athlete_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("permission_role", sa.String(length=32), nullable=False, server_default="viewer"),
        sa.Column("can_view", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("can_edit", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("can_sync_garmin", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "athlete_id", name="uq_user_athlete_permission_user_athlete"),
    )
    op.create_index(op.f("ix_user_athlete_permissions_user_id"), "user_athlete_permissions", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_athlete_permissions_athlete_id"), "user_athlete_permissions", ["athlete_id"], unique=False)

    op.add_column("garmin_accounts", sa.Column("garmin_email", sa.String(length=255), nullable=True))
    op.add_column("garmin_accounts", sa.Column("garmin_password_encrypted", sa.String(length=1024), nullable=True))
    op.add_column("garmin_accounts", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"))
    op.add_column("garmin_accounts", sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE garmin_accounts SET garmin_email = username WHERE garmin_email IS NULL AND username IS NOT NULL")
    op.execute(
        "UPDATE garmin_accounts "
        "SET garmin_password_encrypted = encrypted_password "
        "WHERE garmin_password_encrypted IS NULL AND encrypted_password IS NOT NULL"
    )
    op.execute("UPDATE garmin_accounts SET is_active = CASE WHEN status = 'active' THEN 1 ELSE 0 END")
    op.execute(
        "UPDATE garmin_accounts "
        "SET last_sync_at = CASE "
        "WHEN last_activity_sync_at IS NOT NULL AND last_health_sync_at IS NOT NULL THEN "
        "CASE WHEN last_activity_sync_at >= last_health_sync_at THEN last_activity_sync_at ELSE last_health_sync_at END "
        "ELSE COALESCE(last_activity_sync_at, last_health_sync_at) END"
    )


def downgrade() -> None:
    op.drop_column("garmin_accounts", "last_sync_at")
    op.drop_column("garmin_accounts", "is_active")
    op.drop_column("garmin_accounts", "garmin_password_encrypted")
    op.drop_column("garmin_accounts", "garmin_email")

    op.drop_index(op.f("ix_user_athlete_permissions_athlete_id"), table_name="user_athlete_permissions")
    op.drop_index(op.f("ix_user_athlete_permissions_user_id"), table_name="user_athlete_permissions")
    op.drop_table("user_athlete_permissions")

    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
