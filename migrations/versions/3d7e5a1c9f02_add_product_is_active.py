"""Add product.is_active

Revision ID: 3d7e5a1c9f02
Revises: 9f1a6d2c8b4e
Create Date: 2026-07-02 00:00:00.000002

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3d7e5a1c9f02'
down_revision = '9f1a6d2c8b4e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))

    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.alter_column('is_active', server_default=None)


def downgrade():
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_column('is_active')
