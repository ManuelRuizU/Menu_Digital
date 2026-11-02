"""seasonal decorations

Revision ID: d5b8f3a2c6e1
Revises: c4a9e2f7b1d3
Create Date: 2026-11-02 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5b8f3a2c6e1'
down_revision = 'c4a9e2f7b1d3'
branch_labels = None
depends_on = None


def upgrade():
    # The master switch starts off and the celebration table empty: the menu looks
    # exactly as before until the owner switches something on.
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seasonal_decor_enabled', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    op.create_table(
        'celebration',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('motif', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('start_md', sa.String(length=5), nullable=True),
        sa.Column('end_md', sa.String(length=5), nullable=True),
        sa.Column('days_before', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('emojis', sa.String(length=64), nullable=True),
        sa.Column('accent', sa.String(length=7), nullable=True),
        sa.Column('ambient', sa.Boolean(), nullable=False),
        sa.Column('burst', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('celebration')
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('seasonal_decor_enabled')
