"""Add product.sold_out

Revision ID: 5b8e3f7a1c4d
Revises: 3e7f1b9c2a56
Create Date: 2026-07-03 00:00:00.000008

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5b8e3f7a1c4d'
down_revision = '3e7f1b9c2a56'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sold_out', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_column('sold_out')
