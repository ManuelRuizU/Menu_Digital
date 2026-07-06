"""Replace user.opens_at/closes_at with a per-day-of-week business_hours table

Revision ID: 7f3d9a2c5e84
Revises: 4c8b1e6a9f27
Create Date: 2026-07-06 00:00:00.000024

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7f3d9a2c5e84'
down_revision = '4c8b1e6a9f27'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'business_hours',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('day_of_week', sa.Integer(), nullable=False, unique=True),
        sa.Column('opens_at', sa.String(length=5), nullable=True),
        sa.Column('closes_at', sa.String(length=5), nullable=True),
    )

    # Carry the old single daily range over to all 7 days, so existing installs keep
    # behaving exactly the same until the owner customizes individual days.
    connection = op.get_bind()
    existing = connection.execute(sa.text('SELECT opens_at, closes_at FROM user LIMIT 1')).fetchone()
    opens_at, closes_at = (existing[0], existing[1]) if existing else (None, None)

    business_hours_table = sa.table(
        'business_hours',
        sa.column('day_of_week', sa.Integer),
        sa.column('opens_at', sa.String),
        sa.column('closes_at', sa.String),
    )
    op.bulk_insert(
        business_hours_table,
        [{'day_of_week': day, 'opens_at': opens_at, 'closes_at': closes_at} for day in range(7)],
    )

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('opens_at')
        batch_op.drop_column('closes_at')


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('opens_at', sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column('closes_at', sa.String(length=5), nullable=True))
    op.drop_table('business_hours')
