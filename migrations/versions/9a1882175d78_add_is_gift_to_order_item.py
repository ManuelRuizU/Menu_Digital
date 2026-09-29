"""add is_gift to order_item

Revision ID: 9a1882175d78
Revises: d10baf81c6af
Create Date: 2026-09-29 03:10:54.224495

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9a1882175d78'
down_revision = 'd10baf81c6af'
branch_labels = None
depends_on = None


def upgrade():
    # server_default='0' so every existing row gets False; the real gifts among them
    # are marked right below.
    with op.batch_alter_table('order_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_gift', sa.Boolean(), nullable=False,
                                       server_default=sa.text('0')))

    # Backfill with the same heuristic the panel used until now (price 0 AND the
    # product currently configured as the gift) - otherwise past orders lose their 🎁
    # badge and keep being miscounted when edited. Gifts of a PREVIOUS gift product
    # aren't marked: the old heuristic didn't recognize them either, nothing is lost.
    # "user" quoted because it's a reserved word outside SQLite.
    op.execute(
        'UPDATE order_item SET is_gift = 1 '
        'WHERE price = 0 AND product_id = '
        '(SELECT gift_product_id FROM "user" WHERE is_owner = 1)'
    )


def downgrade():
    with op.batch_alter_table('order_item', schema=None) as batch_op:
        batch_op.drop_column('is_gift')
