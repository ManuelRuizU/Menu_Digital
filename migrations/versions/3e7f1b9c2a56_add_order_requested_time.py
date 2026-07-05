"""Add order.requested_time

Revision ID: 3e7f1b9c2a56
Revises: 6c9d2a4e8f71
Create Date: 2026-07-02 00:00:00.000007

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3e7f1b9c2a56'
down_revision = '6c9d2a4e8f71'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('requested_time', sa.String(length=5), nullable=True))


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('requested_time')
