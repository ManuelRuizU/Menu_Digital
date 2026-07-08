"""snapshot product_name en OrderItem

Revision ID: bd909043927c
Revises: a222c27e8aed
Create Date: 2026-07-08 13:03:56.661626

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd909043927c'
down_revision = 'a222c27e8aed'
branch_labels = None
depends_on = None


def upgrade():
    # product_id becomes optional - deleting a product should no longer be blocked by
    # (or corrupt) old orders that already snapshot everything they need in this table.
    with op.batch_alter_table('order_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('product_name', sa.String(length=100), nullable=True))
        batch_op.alter_column('product_id',
               existing_type=sa.INTEGER(),
               nullable=True)

    # Backfill existing rows from the product they still point to.
    op.execute(
        'UPDATE order_item SET product_name = ('
        'SELECT name FROM product WHERE product.id = order_item.product_id'
        ') WHERE product_name IS NULL'
    )

    connection = op.get_bind()
    missing = connection.execute(
        sa.text('SELECT COUNT(*) FROM order_item WHERE product_name IS NULL')
    ).scalar()
    if missing:
        raise RuntimeError(
            f'{missing} order_item row(s) still have product_name NULL after backfill - '
            'their product_id points to nothing (or was already NULL). Fix the data '
            'before re-running this migration; refusing to add a NOT NULL constraint '
            'that would fail.'
        )

    with op.batch_alter_table('order_item', schema=None) as batch_op:
        batch_op.alter_column('product_name',
               existing_type=sa.String(length=100),
               nullable=False)


def downgrade():
    with op.batch_alter_table('order_item', schema=None) as batch_op:
        batch_op.alter_column('product_id',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.drop_column('product_name')
