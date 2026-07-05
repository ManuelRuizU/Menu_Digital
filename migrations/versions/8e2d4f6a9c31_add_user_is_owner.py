"""Add user.is_owner and grandfather existing admins as owners

Revision ID: 8e2d4f6a9c31
Revises: 4a7c1e9b3d56
Create Date: 2026-07-03 00:00:00.000013

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8e2d4f6a9c31'
down_revision = '4a7c1e9b3d56'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_owner', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute('UPDATE "user" SET is_owner = 1 WHERE is_admin = 1')


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('is_owner')
