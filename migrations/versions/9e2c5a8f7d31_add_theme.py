"""Add user.theme (visual theme for the public menu)

Revision ID: 9e2c5a8f7d31
Revises: 2d7e6f9a4c18
Create Date: 2026-07-06 20:00:00.000022

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9e2c5a8f7d31'
down_revision = '2d7e6f9a4c18'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('theme', sa.String(length=20), nullable=False, server_default='oscuro'))
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('theme', server_default=None)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('theme')
