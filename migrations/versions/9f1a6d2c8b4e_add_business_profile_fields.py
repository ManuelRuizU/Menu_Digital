"""Add business_name, address, logo_filename to user

Revision ID: 9f1a6d2c8b4e
Revises: 7c2b4e9a1d3f
Create Date: 2026-07-02 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f1a6d2c8b4e'
down_revision = '7c2b4e9a1d3f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('business_name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('address', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('logo_filename', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('logo_filename')
        batch_op.drop_column('address')
        batch_op.drop_column('business_name')
