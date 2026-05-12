"""merge heads after modality migration

Revision ID: 9c21a43f5afe
Revises: 1a2b3c4d5e7f, fa1b2c3d4e5f
Create Date: 2026-05-06 00:31:33.385568

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = '9c21a43f5afe'
down_revision = ('1a2b3c4d5e7f', 'fa1b2c3d4e5f')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
