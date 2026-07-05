"""Add product.is_featured and user.min_delivery_order

Revision ID: 7d4a9c2e6f18
Revises: 5b8e3f7a1c4d
Create Date: 2026-07-03 00:00:00.000009

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7d4a9c2e6f18'
down_revision = '5b8e3f7a1c4d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_featured', sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('min_delivery_order', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('min_delivery_order')

    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_column('is_featured')
