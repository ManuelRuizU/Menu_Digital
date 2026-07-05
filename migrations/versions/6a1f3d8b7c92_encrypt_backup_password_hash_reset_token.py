"""Rename user.backup_email_password to backup_email_password_encrypted, and
user.reset_token to reset_token_hash - both now store a transformed value
(encrypted / hashed) instead of the raw secret, per security audit.

Revision ID: 6a1f3d8b7c92
Revises: 2b6e9a4d8f31
Create Date: 2026-07-05 02:40:00.000019

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6a1f3d8b7c92'
down_revision = '2b6e9a4d8f31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('backup_email_password', new_column_name='backup_email_password_encrypted')
        batch_op.alter_column('reset_token', new_column_name='reset_token_hash')


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('backup_email_password_encrypted', new_column_name='backup_email_password')
        batch_op.alter_column('reset_token_hash', new_column_name='reset_token')
