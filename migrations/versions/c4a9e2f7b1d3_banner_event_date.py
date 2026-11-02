"""banner event date and reminder

Revision ID: c4a9e2f7b1d3
Revises: b3f8d1e6a4c2
Create Date: 2026-11-02 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4a9e2f7b1d3'
down_revision = 'b3f8d1e6a4c2'
branch_labels = None
depends_on = None


def upgrade():
    # Two new columns only: the banners already there get no event and no reminder
    # button, so they look exactly as before.
    with op.batch_alter_table('hero_banner', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('show_reminder', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('hero_banner', schema=None) as batch_op:
        batch_op.drop_column('show_reminder')
        batch_op.drop_column('event_date')
