# app\models.py
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from .extensions import db
from werkzeug.security import generate_password_hash, check_password_hash

BUSINESS_TZ = ZoneInfo('America/Santiago')


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_owner = db.Column(db.Boolean, nullable=False, default=False)
    whatsapp_number = db.Column(db.String(20), nullable=True)
    business_name = db.Column(db.String(120), nullable=True)
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
    min_delivery_order = db.Column(db.Float, nullable=True)
    opens_at = db.Column(db.String(5), nullable=True)
    closes_at = db.Column(db.String(5), nullable=True)
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
    price = db.Column(db.Float, nullable=False)
    image_filename = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sold_out = db.Column(db.Boolean, nullable=False, default=False)
    is_featured = db.Column(db.Boolean, nullable=False, default=False)
    stock_quantity = db.Column(db.Integer, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('subcategory.id'), nullable=True)
    category = db.relationship('Category')
    orders = db.relationship('OrderItem', backref='product', lazy=True)

    def __repr__(self):
        return f'<Product {self.name}>'

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    delivery_mode = db.Column(db.String(20), nullable=False, default='retira')
    payment_method = db.Column(db.String(30), nullable=True)
    shipping_cost = db.Column(db.Float, nullable=False, default=0)
    order_items = db.relationship('OrderItem', backref='order', lazy=True)
    total_price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Pending')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    cash_amount = db.Column(db.Float, nullable=True)
    requested_time = db.Column(db.String(5), nullable=True)
    requested_time_end = db.Column(db.String(5), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    @property
    def phone_digits(self):
        return re.sub(r'\D', '', self.phone or '')

    @property
    def created_at_local(self):
        """created_at is stored in naive UTC; render it in the business's own timezone."""
        return self.created_at.replace(tzinfo=ZoneInfo('UTC')).astimezone(BUSINESS_TZ)

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
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<OrderItem {self.id}>'


class DeliveryRadiusTier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    min_km = db.Column(db.Float, nullable=False)
    max_km = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<DeliveryRadiusTier {self.min_km}-{self.max_km}km>'


class DeliveryZone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    geojson = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f'<DeliveryZone {self.name}>'


class Courier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    whatsapp_number = db.Column(db.String(20), nullable=False)

    def __repr__(self):
        return f'<Courier {self.name}>'
