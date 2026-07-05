"""Add business location and delivery radius tiers / polygon zones

Revision ID: 5b8c3e7a2d41
Revises: 3d7e5a1c9f02
Create Date: 2026-07-02 00:00:00.000003

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5b8c3e7a2d41'
down_revision = '3d7e5a1c9f02'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('latitude', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('longitude', sa.Float(), nullable=True))

    op.create_table(
        'delivery_radius_tier',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('min_km', sa.Float(), nullable=False),
        sa.Column('max_km', sa.Float(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'delivery_zone',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('geojson', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('delivery_zone')
    op.drop_table('delivery_radius_tier')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('longitude')
        batch_op.drop_column('latitude')
