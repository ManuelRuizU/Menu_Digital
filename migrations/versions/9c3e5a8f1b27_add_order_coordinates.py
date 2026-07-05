"""Add order.latitude and order.longitude

Revision ID: 9c3e5a8f1b27
Revises: 7d4a9c2e6f18
Create Date: 2026-07-03 00:00:00.000010

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c3e5a8f1b27'
down_revision = '7d4a9c2e6f18'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('latitude', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('longitude', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('longitude')
        batch_op.drop_column('latitude')
