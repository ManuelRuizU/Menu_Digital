"""add description to subcategory

Revision ID: 549634a3ed05
Revises: 458953ce6811
Create Date: 2026-10-14 13:17:58.843104

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '549634a3ed05'
down_revision = '458953ce6811'
branch_labels = None
depends_on = None


def upgrade():
    # Optional, so no default and no backfill: existing subcategories stay NULL
    # (no description) until the owner writes one.
    with op.batch_alter_table('subcategory', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('subcategory', schema=None) as batch_op:
        batch_op.drop_column('description')
