# app\models.py
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from .extensions import db
from werkzeug.security import generate_password_hash, check_password_hash

BUSINESS_TZ = ZoneInfo('America/Santiago')

# Visual themes for the public menu (app/static/css/menu.css) - the colors here are
# just the suggested defaults shown in the color pickers; the owner can still override them.
THEMES = {
    'oscuro': {'label': 'Oscuro moderno', 'primary': '#4ecdc4', 'accent': '#ff6b6b'},
    'claro': {'label': 'Cálido artesanal', 'primary': '#5c7c5a', 'accent': '#8a6b4f'},
    'urbano': {'label': 'Urbano llamativo', 'primary': '#ffcc00', 'accent': '#ff3d1a'},
    'cafeteria': {'label': 'Minimalista café', 'primary': '#5b7c8f', 'accent': '#5b7c8f'},
    'trattoria': {'label': 'Trattoria clásica', 'primary': '#a5312f', 'accent': '#3f6b45'},
}

# How many minutes wide each Agenda time slot is (Paso 2b) - a fixed list, not a
# free field, so the Agenda's grid math never has to handle an arbitrary value.
AGENDA_BLOCK_MINUTES_OPTIONS = [5, 10, 15, 20, 30, 60]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_owner = db.Column(db.Boolean, nullable=False, default=False)
    whatsapp_number = db.Column(db.String(20), nullable=True)
    business_name = db.Column(db.String(120), nullable=True)
    slogan = db.Column(db.String(200), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    logo_filename = db.Column(db.String(255), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    primary_color = db.Column(db.String(7), nullable=True)
    accent_color = db.Column(db.String(7), nullable=True)
    accepts_cash = db.Column(db.Boolean, nullable=False, default=True)
    accepts_transfer = db.Column(db.Boolean, nullable=False, default=True)
    accepts_card = db.Column(db.Boolean, nullable=False, default=True)
    bank_details = db.Column(db.Text, nullable=True)
    min_delivery_order = db.Column(db.Integer, nullable=True)
    printer_ip = db.Column(db.String(45), nullable=True)
    printer_width_mm = db.Column(db.Integer, nullable=True)
    backup_email_host = db.Column(db.String(120), nullable=True)
    backup_email_port = db.Column(db.Integer, nullable=True)
    backup_email_address = db.Column(db.String(120), nullable=True)
    backup_email_password_encrypted = db.Column(db.String(255), nullable=True)
    backup_email_to = db.Column(db.String(120), nullable=True)
    backup_last_sent_at = db.Column(db.DateTime, nullable=True)
    reset_token_hash = db.Column(db.String(64), nullable=True)
    reset_token_expires_at = db.Column(db.DateTime, nullable=True)
    is_closed_temporarily = db.Column(db.Boolean, nullable=False, default=False)
    closed_message = db.Column(db.Text, nullable=True)
    theme = db.Column(db.String(20), nullable=False, default='oscuro')
    agenda_block_minutes = db.Column(db.Integer, nullable=False, default=10)
    gift_threshold_amount = db.Column(db.Integer, nullable=True)
    gift_product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    gift_product = db.relationship('Product', foreign_keys=[gift_product_id])

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def backup_email_password(self):
        """The SMTP app password, transparently encrypted at rest (app/crypto.py) -
        unlike the login password, this one has to be reversible to actually send email."""
        from app.crypto import decrypt_secret
        return decrypt_secret(self.backup_email_password_encrypted)

    @backup_email_password.setter
    def backup_email_password(self, value):
        from app.crypto import encrypt_secret
        self.backup_email_password_encrypted = encrypt_secret(value)

    def __repr__(self):
        return f'<User {self.username}>'


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    subcategories = db.relationship('Subcategory', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'

class Subcategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    products = db.relationship('Product', backref='subcategory', lazy=True)

    def __repr__(self):
        return f'<Subcategory {self.name}>'

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Integer, nullable=False)
    original_price = db.Column(db.Integer, nullable=True)
    image_filename = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sold_out = db.Column(db.Boolean, nullable=False, default=False)
    is_featured = db.Column(db.Boolean, nullable=False, default=False)
    stock_quantity = db.Column(db.Integer, nullable=True)
    prep_minutes = db.Column(db.Integer, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('subcategory.id'), nullable=True)
    category = db.relationship('Category')
    orders = db.relationship('OrderItem', backref='product', lazy=True)
    option_groups = db.relationship('ProductOptionGroup', backref='product', lazy=True,
                                     cascade='all, delete-orphan', order_by='ProductOptionGroup.id')

    def __repr__(self):
        return f'<Product {self.name}>'


class ProductOptionGroup(db.Model):
    """A named set of choices for a product - e.g. "Tamaño" (required, pick one) or
    "Extras" (optional, pick several). Optional per product - most products have none."""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    required = db.Column(db.Boolean, nullable=False, default=False)
    multi_select = db.Column(db.Boolean, nullable=False, default=False)
    options = db.relationship('ProductOption', backref='group', lazy=True,
                               cascade='all, delete-orphan', order_by='ProductOption.id')

    def __repr__(self):
        return f'<ProductOptionGroup {self.name}>'


class ProductOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('product_option_group.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    price_delta = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f'<ProductOption {self.name}>'

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    delivery_mode = db.Column(db.String(20), nullable=False, default='retira')
    payment_method = db.Column(db.String(30), nullable=True)
    shipping_cost = db.Column(db.Integer, nullable=False, default=0)
    order_items = db.relationship('OrderItem', backref='order', lazy=True)
    total_price = db.Column(db.Integer, nullable=False)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=True)
    discount_amount = db.Column(db.Integer, nullable=False, default=0)
    bundle_discount_amount = db.Column(db.Integer, nullable=False, default=0)
    coupon = db.relationship('Coupon')
    status = db.Column(db.String(20), nullable=False, default='Pending')
    payment_status = db.Column(db.String(10), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    # The Santiago calendar day confirmed_at falls on, computed in Python (never
    # DATE(confirmed_at) in SQL - that would be the UTC day, wrong near midnight).
    # Paired with daily_number under a UNIQUE constraint so the DB - not the app
    # server - is what guarantees no two orders share a number on the same day.
    confirmed_date = db.Column(db.Date, nullable=True, index=True)
    daily_number = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    cash_amount = db.Column(db.Integer, nullable=True)
    requested_time = db.Column(db.String(5), nullable=True)
    requested_time_end = db.Column(db.String(5), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('confirmed_date', 'daily_number'),
    )

    @property
    def phone_digits(self):
        return re.sub(r'\D', '', self.phone or '')

    @property
    def created_at_local(self):
        """created_at is stored in naive UTC; render it in the business's own timezone."""
        return self.created_at.replace(tzinfo=ZoneInfo('UTC')).astimezone(BUSINESS_TZ)

    @property
    def confirmed_at_local(self):
        """confirmed_at is stored in naive UTC like created_at - None if never confirmed."""
        if self.confirmed_at is None:
            return None
        return self.confirmed_at.replace(tzinfo=ZoneInfo('UTC')).astimezone(BUSINESS_TZ)

    @property
    def requested_time_label(self):
        if not self.requested_time:
            return 'Lo antes posible'
        if self.requested_time_end:
            return f'{self.requested_time} - {self.requested_time_end}'
        return self.requested_time

    def __repr__(self):
        return f'<Order {self.id}>'

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    product_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)  # per-unit price, already including any selected options
    selected_options = db.relationship('OrderItemOption', backref='order_item', lazy=True,
                                        cascade='all, delete-orphan')

    def __repr__(self):
        return f'<OrderItem {self.id}>'


class OrderItemOption(db.Model):
    """Snapshot of a chosen option at order time (name + price) - independent of
    ProductOption, which the owner could edit or delete later without altering history."""
    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_item.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    price_delta = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f'<OrderItemOption {self.name}>'


coupon_product = db.Table(
    'coupon_product',
    db.Column('coupon_id', db.Integer, db.ForeignKey('coupon.id'), primary_key=True),
    db.Column('product_id', db.Integer, db.ForeignKey('product.id'), primary_key=True),
)


class Coupon(db.Model):
    """A promo code the customer types in the cart (e.g. "PRIMERACOMPRA" or "DIADELSUSHI10").

    scope='order' discounts the whole purchase (products, and shipping too only if
    applies_to_shipping is set - off by default, since shipping is a pass-through to
    the courier, not the business's own margin); scope='products' discounts only the
    line total of the specific products attached below and never touches shipping.
    All limits (max_total_uses, max_uses_per_customer, valid_from/valid_until) are
    independent and optional - a coupon can use any combination, or none at all."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    discount_percent = db.Column(db.Float, nullable=False)
    scope = db.Column(db.String(10), nullable=False, default='order')
    applies_to_shipping = db.Column(db.Boolean, nullable=False, default=False)
    products = db.relationship('Product', secondary=coupon_product, lazy='joined', backref='coupons')
    max_total_uses = db.Column(db.Integer, nullable=True)
    max_uses_per_customer = db.Column(db.Integer, nullable=True)
    valid_from = db.Column(db.Date, nullable=True)
    valid_until = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    show_in_banner = db.Column(db.Boolean, nullable=False, default=False)
    banner_image_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    redemptions = db.relationship('CouponRedemption', backref='coupon', lazy=True, cascade='all, delete-orphan')

    @property
    def total_uses(self):
        return len(self.redemptions)

    def __repr__(self):
        return f'<Coupon {self.code}>'


class CouponRedemption(db.Model):
    """One row per time a coupon was actually applied to an order - the source of truth for
    both usage limits above, instead of a simple counter that could drift out of sync."""
    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    phone_digits = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<CouponRedemption coupon_id={self.coupon_id} order_id={self.order_id}>'


bundle_promo_product = db.Table(
    'bundle_promo_product',
    db.Column('bundle_promo_id', db.Integer, db.ForeignKey('bundle_promo.id'), primary_key=True),
    db.Column('product_id', db.Integer, db.ForeignKey('product.id'), primary_key=True),
)


class BundlePromo(db.Model):
    """A "2x1"/"3x2"-style automatic promotion (no code needed): buy `buy_quantity` units
    across the attached products, pay for only `pay_quantity` of them - the cheapest
    units in each complete group are the ones that come out free. Applies automatically
    whenever the cart has enough matching items; never requires the customer to do anything."""
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(80), nullable=False)
    buy_quantity = db.Column(db.Integer, nullable=False)
    pay_quantity = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    valid_from = db.Column(db.Date, nullable=True)
    valid_until = db.Column(db.Date, nullable=True)
    products = db.relationship('Product', secondary=bundle_promo_product, lazy='joined', backref='bundle_promos')

    def __repr__(self):
        return f'<BundlePromo {self.label}>'


class DeliveryRadiusTier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    min_km = db.Column(db.Float, nullable=False)
    max_km = db.Column(db.Float, nullable=False)
    price = db.Column(db.Integer, nullable=False)

    def __repr__(self):
        return f'<DeliveryRadiusTier {self.min_km}-{self.max_km}km>'


class DeliveryZone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    geojson = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f'<DeliveryZone {self.name}>'


class Courier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    whatsapp_number = db.Column(db.String(20), nullable=False)

    def __repr__(self):
        return f'<Courier {self.name}>'


DAY_NAMES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


class BusinessHours(db.Model):
    """One row per day of the week (0=Monday...6=Sunday, matching date.weekday()).
    Both opens_at/closes_at null means closed that whole day."""
    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.Integer, nullable=False, unique=True)
    opens_at = db.Column(db.String(5), nullable=True)
    closes_at = db.Column(db.String(5), nullable=True)

    @property
    def day_name(self):
        return DAY_NAMES[self.day_of_week]

    @property
    def is_closed(self):
        return not self.opens_at or not self.closes_at

    def __repr__(self):
        return f'<BusinessHours {self.day_name}>'
