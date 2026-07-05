"""Add user.is_closed_temporarily and closed_message

Revision ID: 8f4c1a9e3b56
Revises: 6a1f3d8b7c92
Create Date: 2026-07-06 00:00:00.000020

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8f4c1a9e3b56'
down_revision = '6a1f3d8b7c92'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_closed_temporarily', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('closed_message', sa.Text(), nullable=True))
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('is_closed_temporarily', server_default=None)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('closed_message')
        batch_op.drop_column('is_closed_temporarily')
