"""Add product option groups/options (variants, extras) and order item options

Revision ID: 2d7e6f9a4c18
Revises: 8f4c1a9e3b56
Create Date: 2026-07-06 12:00:00.000021

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2d7e6f9a4c18'
down_revision = '8f4c1a9e3b56'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'product_option_group',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('product.id'), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('multi_select', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        'product_option',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('product_option_group.id'), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('price_delta', sa.Float(), nullable=False, server_default='0'),
    )
    op.create_table(
        'order_item_option',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_item_id', sa.Integer(), sa.ForeignKey('order_item.id'), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('price_delta', sa.Float(), nullable=False, server_default='0'),
    )


def downgrade():
    op.drop_table('order_item_option')
    op.drop_table('product_option')
    op.drop_table('product_option_group')
