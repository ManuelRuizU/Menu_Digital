"""bundle promo featured quantity

Revision ID: 3c5e1f7a9b20
Revises: 8d9229ceab0b
Create Date: 2026-10-20 03:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3c5e1f7a9b20'
down_revision = '8d9229ceab0b'
branch_labels = None
depends_on = None


def upgrade():
    # server_default='1': every existing promo keeps showing the regular price on the
    # menu card, exactly as before.
    with op.batch_alter_table('bundle_promo', schema=None) as batch_op:
        batch_op.add_column(sa.Column('featured_quantity', sa.Integer(), nullable=False, server_default='1'))


def downgrade():
    with op.batch_alter_table('bundle_promo', schema=None) as batch_op:
        batch_op.drop_column('featured_quantity')
