"""coupon attempt log

Revision ID: b3f8d1e6a4c2
Revises: 9e4b7c1d2a60
Create Date: 2026-10-30 03:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3f8d1e6a4c2'
down_revision = '9e4b7c1d2a60'
branch_labels = None
depends_on = None


def upgrade():
    # A new table only - the log starts empty (the coupon redemptions already there
    # keep counting as uses, as before).
    op.create_table(
        'coupon_attempt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('source', sa.String(length=12), nullable=True),
        sa.Column('result', sa.String(length=10), nullable=False),
        sa.Column('reason', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('coupon_attempt', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_coupon_attempt_created_at'), ['created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('coupon_attempt', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_coupon_attempt_created_at'))
    op.drop_table('coupon_attempt')
