"""Replace user.prep_time_estimate with opens_at/closes_at

Revision ID: 4a7c1e9b3d56
Revises: 2f6b8d4a9e13
Create Date: 2026-07-03 00:00:00.000012

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4a7c1e9b3d56'
down_revision = '2f6b8d4a9e13'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('opens_at', sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column('closes_at', sa.String(length=5), nullable=True))
        batch_op.drop_column('prep_time_estimate')


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('prep_time_estimate', sa.String(length=50), nullable=True))
        batch_op.drop_column('closes_at')
        batch_op.drop_column('opens_at')
