"""Add courier table

Revision ID: 6f1b8a3d7e42
Revises: 8e2d4f6a9c31
Create Date: 2026-07-03 00:00:00.000014

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6f1b8a3d7e42'
down_revision = '8e2d4f6a9c31'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'courier',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('whatsapp_number', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('courier')
