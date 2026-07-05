"""Add product.stock_quantity and user backup-email settings

Revision ID: 9d4f7b2e5c83
Revises: 7a2c5e9b4d16
Create Date: 2026-07-05 00:00:00.000017

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9d4f7b2e5c83'
down_revision = '7a2c5e9b4d16'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stock_quantity', sa.Integer(), nullable=True))

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('backup_email_host', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('backup_email_port', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('backup_email_address', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('backup_email_password', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('backup_email_to', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('backup_last_sent_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('backup_last_sent_at')
        batch_op.drop_column('backup_email_to')
        batch_op.drop_column('backup_email_password')
        batch_op.drop_column('backup_email_address')
        batch_op.drop_column('backup_email_port')
        batch_op.drop_column('backup_email_host')

    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_column('stock_quantity')
