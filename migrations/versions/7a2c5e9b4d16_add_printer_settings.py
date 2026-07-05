"""Add user.printer_ip and user.printer_width_mm

Revision ID: 7a2c5e9b4d16
Revises: 3d9e6c4a1f85
Create Date: 2026-07-04 00:00:00.000016

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a2c5e9b4d16'
down_revision = '3d9e6c4a1f85'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('printer_ip', sa.String(length=45), nullable=True))
        batch_op.add_column(sa.Column('printer_width_mm', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('printer_width_mm')
        batch_op.drop_column('printer_ip')
