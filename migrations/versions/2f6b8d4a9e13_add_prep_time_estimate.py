"""Add user.prep_time_estimate

Revision ID: 2f6b8d4a9e13
Revises: 9c3e5a8f1b27
Create Date: 2026-07-03 00:00:00.000011

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2f6b8d4a9e13'
down_revision = '9c3e5a8f1b27'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('prep_time_estimate', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('prep_time_estimate')
