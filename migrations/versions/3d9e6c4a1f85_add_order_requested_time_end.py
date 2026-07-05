"""Add order.requested_time_end for flexible delivery time ranges

Revision ID: 3d9e6c4a1f85
Revises: 6f1b8a3d7e42
Create Date: 2026-07-03 00:00:00.000015

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3d9e6c4a1f85'
down_revision = '6f1b8a3d7e42'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('requested_time_end', sa.String(length=5), nullable=True))


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('requested_time_end')
