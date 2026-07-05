"""Add customizable brand colors to user

Revision ID: 8a2f4c6e9b13
Revises: 5b8c3e7a2d41
Create Date: 2026-07-02 00:00:00.000004

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8a2f4c6e9b13'
down_revision = '5b8c3e7a2d41'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('primary_color', sa.String(length=7), nullable=True))
        batch_op.add_column(sa.Column('accent_color', sa.String(length=7), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('accent_color')
        batch_op.drop_column('primary_color')
