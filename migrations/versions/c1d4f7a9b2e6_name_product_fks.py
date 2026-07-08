"""name unnamed constraints on order_item, coupon_product, bundle_promo_product,
user, coupon, business_hours

Revision ID: c1d4f7a9b2e6
Revises: bd909043927c
Create Date: 2026-07-08 13:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d4f7a9b2e6'
down_revision = 'bd909043927c'
branch_labels = None
depends_on = None


# Same convention as app/extensions.py - kept as a literal copy here (not imported)
# because migrations must stay runnable against whatever the models looked like at
# the time they were written, independent of later changes to app code.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def upgrade():
    # No column/type/nullable/ondelete changes - recreate='always' forces the
    # SQLite batch "copy into a new table" dance to happen even though no
    # individual column operation is queued, purely so naming_convention gets
    # applied to the constraints these tables already have. user.gift_product_id
    # already carries an explicit name (fk_user_gift_product_id_product, given by
    # migration 5f6715ea6111) - naming_convention only fills in names for
    # constraints that don't already have one, so that FK is reflected as-is and
    # comes out unchanged, not duplicated or renamed. order.coupon_id's FK into
    # coupon isn't touched here (order isn't in this list) and isn't affected by
    # recreating coupon: foreign_keys enforcement is off in this app (no PRAGMA
    # foreign_keys=ON is set anywhere yet), so SQLite doesn't validate or cascade
    # anything while coupon is dropped-and-recreated mid-batch, and the row data
    # (including every order.coupon_id value) is copied through untouched either way.
    for table_name in ('order_item', 'coupon_product', 'bundle_promo_product',
                        'user', 'coupon', 'business_hours'):
        with op.batch_alter_table(table_name, schema=None, recreate='always',
                                   naming_convention=NAMING_CONVENTION):
            pass


def downgrade():
    # naming_convention has no "undo" - reflecting the table again would just see
    # the names already applied. To go back to the original unnamed constraints,
    # copy_from is given an explicit Table with no names, matching exactly what
    # db.create_all() would have produced before this migration existed.
    #
    # These Table objects are a snapshot of each table's schema as of THIS
    # revision - if a later migration adds/removes/renames a column, this
    # downgrade() will silently drop that column's data on the way back down
    # (copy_from only copies columns it knows about). Keep that in mind before
    # downgrading past a later migration that touched these six tables.
    metadata = sa.MetaData()

    order_item_unnamed = sa.Table(
        'order_item', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('order_id', sa.Integer, sa.ForeignKey('order.id'), nullable=False),
        sa.Column('product_id', sa.Integer, sa.ForeignKey('product.id'), nullable=True),
        sa.Column('quantity', sa.Integer, nullable=False),
        sa.Column('price', sa.Integer, nullable=False),
        sa.Column('product_name', sa.String(100), nullable=False),
    )
    with op.batch_alter_table('order_item', schema=None, recreate='always',
                               copy_from=order_item_unnamed):
        pass

    coupon_product_unnamed = sa.Table(
        'coupon_product', metadata,
        sa.Column('coupon_id', sa.Integer, sa.ForeignKey('coupon.id'), primary_key=True),
        sa.Column('product_id', sa.Integer, sa.ForeignKey('product.id'), primary_key=True),
    )
    with op.batch_alter_table('coupon_product', schema=None, recreate='always',
                               copy_from=coupon_product_unnamed):
        pass

    bundle_promo_product_unnamed = sa.Table(
        'bundle_promo_product', metadata,
        sa.Column('bundle_promo_id', sa.Integer, sa.ForeignKey('bundle_promo.id'), primary_key=True),
        sa.Column('product_id', sa.Integer, sa.ForeignKey('product.id'), primary_key=True),
    )
    with op.batch_alter_table('bundle_promo_product', schema=None, recreate='always',
                               copy_from=bundle_promo_product_unnamed):
        pass

    # user.gift_product_id already had a name BEFORE this migration (given by
    # migration 5f6715ea6111, not by naming_convention) - keep it named here too,
    # only username/email go back to unnamed. Otherwise downgrade would strip a
    # name this table never got from this migration in the first place.
    user_unnamed = sa.Table(
        'user', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('username', sa.String(64), nullable=False, unique=True),
        sa.Column('email', sa.String(120), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('is_admin', sa.Boolean),
        sa.Column('whatsapp_number', sa.String(20)),
        sa.Column('business_name', sa.String(120)),
        sa.Column('address', sa.String(255)),
        sa.Column('logo_filename', sa.String(255)),
        sa.Column('latitude', sa.Float),
        sa.Column('longitude', sa.Float),
        sa.Column('primary_color', sa.String(7)),
        sa.Column('accent_color', sa.String(7)),
        sa.Column('accepts_cash', sa.Boolean, nullable=False),
        sa.Column('accepts_transfer', sa.Boolean, nullable=False),
        sa.Column('accepts_card', sa.Boolean, nullable=False),
        sa.Column('bank_details', sa.Text),
        sa.Column('min_delivery_order', sa.Integer),
        sa.Column('is_owner', sa.Boolean, nullable=False, server_default=sa.text('0')),
        sa.Column('printer_ip', sa.String(45)),
        sa.Column('printer_width_mm', sa.Integer),
        sa.Column('backup_email_host', sa.String(120)),
        sa.Column('backup_email_port', sa.Integer),
        sa.Column('backup_email_address', sa.String(120)),
        sa.Column('backup_email_password_encrypted', sa.String(255)),
        sa.Column('backup_email_to', sa.String(120)),
        sa.Column('backup_last_sent_at', sa.DateTime),
        sa.Column('reset_token_hash', sa.String(64)),
        sa.Column('reset_token_expires_at', sa.DateTime),
        sa.Column('is_closed_temporarily', sa.Boolean, nullable=False),
        sa.Column('closed_message', sa.Text),
        sa.Column('theme', sa.String(20), nullable=False),
        sa.Column('slogan', sa.String(200)),
        sa.Column('gift_threshold_amount', sa.Integer),
        sa.Column('gift_product_id', sa.Integer,
                  sa.ForeignKey('product.id', name='fk_user_gift_product_id_product')),
    )
    with op.batch_alter_table('user', schema=None, recreate='always',
                               copy_from=user_unnamed):
        pass

    coupon_unnamed = sa.Table(
        'coupon', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('code', sa.String(30), nullable=False, unique=True),
        sa.Column('discount_percent', sa.Float, nullable=False),
        sa.Column('scope', sa.String(10), nullable=False),
        sa.Column('max_total_uses', sa.Integer),
        sa.Column('max_uses_per_customer', sa.Integer),
        sa.Column('valid_from', sa.Date),
        sa.Column('valid_until', sa.Date),
        sa.Column('is_active', sa.Boolean, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('show_in_banner', sa.Boolean, nullable=False, server_default=sa.text('0')),
        sa.Column('banner_image_filename', sa.String(255)),
    )
    with op.batch_alter_table('coupon', schema=None, recreate='always',
                               copy_from=coupon_unnamed):
        pass

    business_hours_unnamed = sa.Table(
        'business_hours', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('day_of_week', sa.Integer, nullable=False, unique=True),
        sa.Column('opens_at', sa.String(5)),
        sa.Column('closes_at', sa.String(5)),
    )
    with op.batch_alter_table('business_hours', schema=None, recreate='always',
                               copy_from=business_hours_unnamed):
        pass
