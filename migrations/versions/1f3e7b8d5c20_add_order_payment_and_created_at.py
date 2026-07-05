"""Add order.payment_method and order.created_at

Revision ID: 1f3e7b8d5c20
Revises: 8a2f4c6e9b13
Create Date: 2026-07-02 00:00:00.000005

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f3e7b8d5c20'
down_revision = '8a2f4c6e9b13'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_method', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column(
            'created_at', sa.DateTime(), nullable=False,
            server_default=datetime.utcnow().isoformat(sep=' '),
        ))

    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.alter_column('created_at', server_default=None)


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('created_at')
        batch_op.drop_column('payment_method')
