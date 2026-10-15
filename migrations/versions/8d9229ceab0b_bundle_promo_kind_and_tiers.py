"""bundle promo kind and tiers

Revision ID: 8d9229ceab0b
Revises: 549634a3ed05
Create Date: 2026-10-14 16:42:40.519222

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8d9229ceab0b'
down_revision = '549634a3ed05'
branch_labels = None
depends_on = None


def upgrade():
    # server_default='buy_pay': every existing promo is a 2x1/3x2 and keeps working
    # exactly as before. buy/pay become nullable because a tiered promo has neither;
    # the existing rows keep their values (batch copies them over).
    with op.batch_alter_table('bundle_promo', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=10), nullable=False,
                                       server_default='buy_pay'))
        batch_op.alter_column('buy_quantity', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('pay_quantity', existing_type=sa.Integer(), nullable=True)
        # What NOT NULL used to guarantee, now per kind: a buy_pay promo still can't
        # lose its numbers, and an unknown kind can't get in at all.
        batch_op.create_check_constraint(
            'ck_bundle_promo_kind_fields',
            "kind IN ('buy_pay', 'tiered') "
            "AND (kind = 'tiered' OR (buy_quantity IS NOT NULL AND pay_quantity IS NOT NULL))")

    op.create_table(
        'bundle_promo_tier',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('promo_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('total_price', sa.Integer(), nullable=False),
        sa.CheckConstraint('quantity >= 2', name='ck_bundle_promo_tier_quantity_min'),
        sa.CheckConstraint('total_price > 0', name='ck_bundle_promo_tier_total_price_positive'),
        sa.ForeignKeyConstraint(['promo_id'], ['bundle_promo.id'],
                                name='fk_bundle_promo_tier_promo_id_bundle_promo'),
        sa.PrimaryKeyConstraint('id', name='pk_bundle_promo_tier'),
        sa.UniqueConstraint('promo_id', 'quantity', name='uq_bundle_promo_tier_promo_id'),
    )


def downgrade():
    # buy/pay can only go back to NOT NULL if no tiered promo exists - and there's no
    # honest buy/pay value to invent for one (a fake "2x1" would start discounting the
    # wrong thing). Refuse instead of silently deleting or rewriting the owner's promos.
    conn = op.get_bind()
    tiered = conn.execute(sa.text("SELECT label FROM bundle_promo WHERE kind = 'tiered'")).fetchall()
    if tiered:
        labels = ', '.join(row[0] for row in tiered)
        raise RuntimeError(
            f'No se puede revertir: existen promos por niveles ({labels}). '
            'Elimínalas desde el panel antes de revertir esta migración.')

    op.drop_table('bundle_promo_tier')
    with op.batch_alter_table('bundle_promo', schema=None) as batch_op:
        batch_op.drop_constraint('ck_bundle_promo_kind_fields', type_='check')
        batch_op.alter_column('pay_quantity', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('buy_quantity', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('kind')
