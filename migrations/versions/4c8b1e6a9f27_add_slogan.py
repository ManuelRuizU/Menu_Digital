"""Add user.slogan

Revision ID: 4c8b1e6a9f27
Revises: 9e2c5a8f7d31
Create Date: 2026-07-06 00:00:00.000023

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4c8b1e6a9f27'
down_revision = '9e2c5a8f7d31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('slogan', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('slogan')
