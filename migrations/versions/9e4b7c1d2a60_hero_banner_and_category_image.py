"""hero banner and category image

Revision ID: 9e4b7c1d2a60
Revises: 5a7d2c9e4f11
Create Date: 2026-10-21 05:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9e4b7c1d2a60'
down_revision = '5a7d2c9e4f11'
branch_labels = None
depends_on = None


def upgrade():
    # No data migration: the manual carousel starts empty (coupons keep showing).
    op.create_table(
        'hero_banner',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('desktop_image', sa.String(length=255), nullable=False),
        sa.Column('mobile_image', sa.String(length=255), nullable=True),
        sa.Column('title', sa.String(length=80), nullable=True),
        sa.Column('text', sa.String(length=200), nullable=True),
        sa.Column('button_label', sa.String(length=30), nullable=True),
        sa.Column('target_type', sa.String(length=10), nullable=False, server_default='none'),
        sa.Column('target_product_id', sa.Integer(), nullable=True),
        sa.Column('target_category_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('valid_from', sa.Date(), nullable=True),
        sa.Column('valid_until', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(['target_product_id'], ['product.id'], name='fk_hero_banner_target_product'),
        sa.ForeignKeyConstraint(['target_category_id'], ['category.id'], name='fk_hero_banner_target_category'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('category', schema=None) as batch_op:
        batch_op.add_column(sa.Column('image_filename', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('category', schema=None) as batch_op:
        batch_op.drop_column('image_filename')
    op.drop_table('hero_banner')
