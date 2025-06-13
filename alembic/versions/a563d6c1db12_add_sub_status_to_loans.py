"""Add sub_status to loans

Revision ID: a563d6c1db12
Revises: 257150e33f92
Create Date: 2025-06-05 12:54:11.704380

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a563d6c1db12'
down_revision: Union[str, None] = '257150e33f92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('loans', sa.Column('sub_status', sa.String(length=50), nullable=True))

def downgrade() -> None:
    op.drop_column('loans', 'sub_status')


