"""Add deleted_at and partial unique index on email

Revision ID: cab82fde7d30
Revises: 0571fd3efd79
Create Date: 2025-06-11 15:49:56.262426

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cab82fde7d30'
down_revision: Union[str, None] = '0571fd3efd79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
