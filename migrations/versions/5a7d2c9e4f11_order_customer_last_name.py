"""order customer last name

Revision ID: 5a7d2c9e4f11
Revises: 3c5e1f7a9b20
Create Date: 2026-10-21 04:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5a7d2c9e4f11'
down_revision = '3c5e1f7a9b20'
branch_labels = None
depends_on = None


def upgrade():
    # Nullable: existing orders keep NULL, with whatever full name they had left in
    # customer_name - old names are never split automatically.
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_last_name', sa.String(length=60), nullable=True))


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('customer_last_name')
