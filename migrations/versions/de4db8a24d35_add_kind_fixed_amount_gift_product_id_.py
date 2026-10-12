"""add kind, fixed_amount, gift_product_id, min_order_amount to coupon

Revision ID: de4db8a24d35
Revises: 9a1882175d78
Create Date: 2026-10-12 12:43:09.873551

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'de4db8a24d35'
down_revision = '9a1882175d78'
branch_labels = None
depends_on = None


def upgrade():
    # server_default='percent' so every existing coupon keeps working exactly as
    # before - they're all percentage coupons today. The other three columns are
    # nullable and stay empty until a coupon actually uses them.
    # discount_percent becomes nullable because fixed/product coupons have no
    # percentage; existing rows keep their value (batch copies them over).
    with op.batch_alter_table('coupon', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=10), nullable=False,
                                       server_default='percent'))
        batch_op.add_column(sa.Column('fixed_amount', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('gift_product_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('min_order_amount', sa.Integer(), nullable=True))
        batch_op.alter_column('discount_percent', existing_type=sa.Float(), nullable=True)
        batch_op.create_foreign_key('fk_coupon_gift_product_id_product', 'product',
                                    ['gift_product_id'], ['id'])


def downgrade():
    # discount_percent can only go back to NOT NULL if no row is NULL - a fixed or
    # product coupon would block the downgrade. Those get 0% AND are deactivated, so
    # rolling back can never leave a live coupon that silently discounts nothing.
    op.execute("UPDATE coupon SET discount_percent = 0, is_active = 0 WHERE discount_percent IS NULL")
    with op.batch_alter_table('coupon', schema=None) as batch_op:
        batch_op.drop_constraint('fk_coupon_gift_product_id_product', type_='foreignkey')
        batch_op.alter_column('discount_percent', existing_type=sa.Float(), nullable=False)
        batch_op.drop_column('min_order_amount')
        batch_op.drop_column('gift_product_id')
        batch_op.drop_column('fixed_amount')
        batch_op.drop_column('kind')
