"""Add soft delete to users + partial unique index

Revision ID: 0571fd3efd79
Revises: 8ab8a535ca30
Create Date: 2025-06-11 15:48:24.092012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0571fd3efd79'
down_revision: Union[str, None] = '8ab8a535ca30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
