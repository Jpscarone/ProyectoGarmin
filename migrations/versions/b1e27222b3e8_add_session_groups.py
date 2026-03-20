"""add session groups

Revision ID: b1e27222b3e8
Revises: c6428e4dd784
Create Date: 2026-03-15 20:20:00.638352

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = 'b1e27222b3e8'
down_revision = 'c6428e4dd784'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'session_groups' not in inspector.get_table_names():
        op.create_table('session_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('training_day_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('group_type', sa.String(length=50), nullable=True),
        sa.Column('group_order', sa.Integer(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['training_day_id'], ['training_days.id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    session_group_indexes = {index["name"] for index in inspector.get_indexes('session_groups')}
    if op.f('ix_session_groups_training_day_id') not in session_group_indexes:
        op.create_index(op.f('ix_session_groups_training_day_id'), 'session_groups', ['training_day_id'], unique=False)

    planned_session_columns = {column["name"] for column in inspector.get_columns('planned_sessions')}
    planned_session_indexes = {index["name"] for index in inspector.get_indexes('planned_sessions')}
    planned_session_fks = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys('planned_sessions')}

    with op.batch_alter_table('planned_sessions', schema=None) as batch_op:
        if 'session_group_id' not in planned_session_columns:
            batch_op.add_column(sa.Column('session_group_id', sa.Integer(), nullable=True))
        if batch_op.f('ix_planned_sessions_session_group_id') not in planned_session_indexes:
            batch_op.create_index(batch_op.f('ix_planned_sessions_session_group_id'), ['session_group_id'], unique=False)
        if 'fk_planned_sessions_session_group_id_session_groups' not in planned_session_fks:
            batch_op.create_foreign_key(
                'fk_planned_sessions_session_group_id_session_groups',
                'session_groups',
                ['session_group_id'],
                ['id'],
            )


def downgrade() -> None:
    with op.batch_alter_table('planned_sessions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_planned_sessions_session_group_id_session_groups', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_planned_sessions_session_group_id'))
        batch_op.drop_column('session_group_id')
    op.drop_index(op.f('ix_session_groups_training_day_id'), table_name='session_groups')
    op.drop_table('session_groups')
