"""add suggest_in_cart to product

Revision ID: 458953ce6811
Revises: de4db8a24d35
Create Date: 2026-10-14 02:31:04.616788

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '458953ce6811'
down_revision = 'de4db8a24d35'
branch_labels = None
depends_on = None


def upgrade():
    # server_default='0' fills every existing row (and any row restored later from a
    # JSON backup taken before this column existed).
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('suggest_in_cart', sa.Boolean(), nullable=False,
                                       server_default=sa.text('0')))

    # Until now the cart's "También te podría interesar" prioritized is_featured -
    # copying it keeps the cart suggesting exactly the same products on the day this
    # deploys. From here on the two flags are independent.
    op.execute('UPDATE product SET suggest_in_cart = is_featured')


def downgrade():
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_column('suggest_in_cart')
