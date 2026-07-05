"""Add user.whatsapp_number, widen password_hash, and switch orders to guest checkout

Revision ID: 7c2b4e9a1d3f
Revises: 1a8007f24517
Create Date: 2026-07-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c2b4e9a1d3f'
down_revision = '1a8007f24517'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('whatsapp_number', sa.String(length=20), nullable=True))
        batch_op.alter_column('password_hash',
                               existing_type=sa.String(length=128),
                               type_=sa.String(length=255),
                               existing_nullable=False)

    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_name', sa.String(length=120), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('phone', sa.String(length=30), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('address', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('delivery_mode', sa.String(length=20), nullable=False, server_default='retira'))
        batch_op.add_column(sa.Column('shipping_cost', sa.Float(), nullable=False, server_default='0'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.alter_column('customer_name', server_default=None)
        batch_op.alter_column('phone', server_default=None)
        batch_op.alter_column('delivery_mode', server_default=None)
        batch_op.alter_column('shipping_cost', server_default=None)


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_order_user_id_user', 'user', ['user_id'], ['id'])
        batch_op.drop_column('shipping_cost')
        batch_op.drop_column('delivery_mode')
        batch_op.drop_column('address')
        batch_op.drop_column('phone')
        batch_op.drop_column('customer_name')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
                               existing_type=sa.String(length=255),
                               type_=sa.String(length=128),
                               existing_nullable=False)
        batch_op.drop_column('whatsapp_number')
