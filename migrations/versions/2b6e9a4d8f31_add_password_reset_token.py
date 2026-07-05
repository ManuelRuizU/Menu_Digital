"""Add user.reset_token and user.reset_token_expires_at

Revision ID: 2b6e9a4d8f31
Revises: 9d4f7b2e5c83
Create Date: 2026-07-05 00:00:00.000018

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2b6e9a4d8f31'
down_revision = '9d4f7b2e5c83'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reset_token', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reset_token_expires_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('reset_token_expires_at')
        batch_op.drop_column('reset_token')
