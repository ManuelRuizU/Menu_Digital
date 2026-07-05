"""Add configurable payment methods, bank details, order notes and cash amount

Revision ID: 6c9d2a4e8f71
Revises: 1f3e7b8d5c20
Create Date: 2026-07-02 00:00:00.000006

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6c9d2a4e8f71'
down_revision = '1f3e7b8d5c20'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('accepts_cash', sa.Boolean(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('accepts_transfer', sa.Boolean(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('accepts_card', sa.Boolean(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('bank_details', sa.Text(), nullable=True))

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('accepts_cash', server_default=None)
        batch_op.alter_column('accepts_transfer', server_default=None)
        batch_op.alter_column('accepts_card', server_default=None)

    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('cash_amount', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('cash_amount')
        batch_op.drop_column('notes')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('bank_details')
        batch_op.drop_column('accepts_card')
        batch_op.drop_column('accepts_transfer')
        batch_op.drop_column('accepts_cash')
