"""Add deleted_at and partial unique index on email

Revision ID: 257150e33f92
Revises: 
Create Date: 2025-06-03 11:14:19.894804
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '257150e33f92'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'role' column
    op.add_column('users', sa.Column('role', sa.String(), nullable=True))

    # Make name NOT NULL
    op.alter_column('users', 'name',
               existing_type=sa.VARCHAR(),
               nullable=False)

    # Drop old unique index on email if it exists
    op.execute("DROP INDEX IF EXISTS ix_users_email")

    # Add deleted_at column
    op.add_column('users', sa.Column('deleted_at', sa.TIMESTAMP(), nullable=True))

    # Add partial unique index on email where deleted_at is NULL
    op.execute("""
        CREATE UNIQUE INDEX idx_users_email_active 
        ON users(email) 
        WHERE deleted_at IS NULL
    """)

    # Drop other indexes as needed (example: upi_id)
    op.drop_index(op.f('ix_users_upi_id'), table_name='users')


def downgrade() -> None:
    # Recreate old indexes
    op.create_index(op.f('ix_users_upi_id'), 'users', ['upi_id'], unique=True)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # Drop partial index
    op.execute("DROP INDEX IF EXISTS idx_users_email_active")

    # Drop deleted_at column
    op.drop_column('users', 'deleted_at')

    # Revert name nullability
    op.alter_column('users', 'name',
               existing_type=sa.VARCHAR(),
               nullable=True)

    # Drop role column
    op.drop_column('users', 'role')
