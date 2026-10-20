# app/catalog/routes.py
import csv
import json
import os
import re
from datetime import datetime
from io import BytesIO, StringIO
from urllib.parse import quote
from zoneinfo import ZoneInfo

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for, Response
from flask_login import current_user, login_required
import qrcode
from PIL import Image, ImageDraw, ImageFont
from escpos.printer import Network
from shapely.geometry import shape
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app import db, limiter
from app.catalog import catalog
from app.decorators import admin_required, owner_required
from app.geocoding import geocode
from app.main.routes import compute_bundle_discount, compute_coupon_discount, get_hours_for_today, \
    has_delivery_configured, _get_active_bundle_promos, _haversine_km, _resolve_selected_options
from app.models import (BUSINESS_TZ, BundlePromo, BundlePromoTier, BusinessHours, Category, Coupon, Courier, DeliveryRadiusTier,
                         DeliveryZone, Order, OrderItem, OrderItemOption, Product, ProductOption, ProductOptionGroup,
                         Subcategory, User)
from app.uploads import save_image
from app.utils import day_range_utc, parse_money

PAYMENT_METHOD_LABELS = {'efectivo': 'Efectivo', 'transferencia': 'Transferencia', 'tarjeta': 'Tarjeta al recibir'}
ORDER_STATUS_LABELS = {'Pending': 'Pendiente', 'Confirmed': 'Confirmado', 'Cancelled': 'Cancelado'}
PAYMENT_STATUS_LABELS = {'pending': 'Pendiente', 'paid': 'Pagado'}


def cash_payment_summary(order):
    """How a cash-paying order's declared cash_amount compares to the final total -
    three distinct outcomes, never collapsed into a single "vuelto" number that hides
    a shortfall as "$0". cash_amount is frozen at checkout on purpose (it's what the
    CUSTOMER declared, not a system value - _recalculate_order_total must never touch
    it), so if the total grows afterward (a product added from the panel, say), the
    gap between what they said and what they now owe has to stay visible everywhere
    this is shown, not silently vanish.

    Returns None when there's nothing cash-related to summarize (not paying cash, or
    no amount was declared). Otherwise a dict: {'status': 'over'|'exact'|'short',
    'amount': int} - 'amount' is the vuelto for 'over', 0 for 'exact', and the
    shortfall (always positive) for 'short'."""
    if order.payment_method != 'efectivo' or not order.cash_amount:
        return None
    difference = order.cash_amount - order.total_price
    if difference > 0:
        return {'status': 'over', 'amount': difference}
    if difference == 0:
        return {'status': 'exact', 'amount': 0}
    return {'status': 'short', 'amount': -difference}

# Groups orders() by what still needs action, not by delivery time: Pending (nothing
# confirmed yet, the thing an encargado can't afford to miss) always on top, then
# Confirmed, then Cancelled (needs no action at all) at the bottom.
ORDERS_STATUS_SORT_PRIORITY = {'Pending': 0, 'Confirmed': 1, 'Cancelled': 2}


def _orders_sort_key(order):
    priority = ORDERS_STATUS_SORT_PRIORITY.get(order.status, len(ORDERS_STATUS_SORT_PRIORITY))
    if order.status == 'Pending':
        # Oldest-waiting-first within the group that most needs attention.
        return (priority, order.created_at)
    # Confirmed and Cancelled both fall back to requested_time - once a sale is
    # closed (or dead), delivery time is what's operationally meaningful to scan by.
    return (priority, order.requested_time or '99:99')


def _build_courier_message(order):
    """Everything a delivery driver needs for one order, as plain WhatsApp text.
    Both callers (_build_courier_links for the single-order link, send_route for the
    batch route) only ever pass already-Confirmed orders, so daily_number is always
    set here - if that assumption is ever broken by a future bug, this should fail
    loudly (AttributeError/None showing up in the message) rather than silently
    paper over it with a fallback."""
    if order.delivery_mode != 'envio':
        return None

    lines = [
        f'Pedido #{order.daily_number}',
        f'Cliente: {order.customer_name}',
        f'Teléfono: {order.phone}',
        f'Hora: {order.requested_time_label}',
    ]
    if order.address:
        lines.append(f'Dirección: {order.address}')
    if order.latitude is not None and order.longitude is not None:
        lines.append(f'Ubicación: https://www.google.com/maps/search/?api=1&query={order.latitude},{order.longitude}')

    payment_label = PAYMENT_METHOD_LABELS.get(order.payment_method, order.payment_method)
    if payment_label:
        payment_line = f'Pago: {payment_label}'
        cash_summary = cash_payment_summary(order)
        if cash_summary is not None:
            if cash_summary['status'] == 'over':
                payment_line += f" - paga con ${order.cash_amount:.0f}, lleva ${cash_summary['amount']:.0f} de vuelto"
            elif cash_summary['status'] == 'exact':
                payment_line += f' - paga con ${order.cash_amount:.0f} justo'
            else:
                payment_line += (f' - OJO: dijo que pagaba con ${order.cash_amount:.0f} pero el total es '
                                  f"${order.total_price:.0f} - faltan ${cash_summary['amount']:.0f}")
        lines.append(payment_line)

    lines.append('')
    lines.append('Productos:')
    for item in order.order_items:
        product_name = item.product_name
        options_text = ''
        if item.selected_options:
            options_text = ' (' + ', '.join(option.name for option in item.selected_options) + ')'
        gift_text = ' (regalo)' if item.is_gift else ''
        lines.append(f'• {item.quantity}x {product_name}{options_text}{gift_text}')

    if order.notes:
        lines.append('')
        lines.append(f'Notas: {order.notes}')

    lines.append('')
    lines.append(f'Total: ${order.total_price:.0f}')

    return chr(10).join(lines)


def _build_courier_links(order, couriers):
    """One WhatsApp link per saved courier, or a single number-less link (modo libre)
    that lets the owner pick any contact, if no couriers are configured yet.
    An unconfirmed order has nothing to hand a driver yet - the sale might not have
    actually closed, so it shouldn't be dispatched."""
    if order.status != 'Confirmed':
        return None
    message = _build_courier_message(order)
    if message is None:
        return None

    encoded = quote(message)
    if couriers:
        return [{'name': courier.name, 'url': f'https://wa.me/{courier.whatsapp_number}?text={encoded}'}
                for courier in couriers]
    return [{'name': None, 'url': f'https://wa.me/?text={encoded}'}]


def _print_order_ticket(order, owner):
    """Print a ticket on the owner's configured WiFi/LAN thermal printer (ESC/POS
    over a raw network socket - no cloud service, no per-print cost).

    Returns (ok, error_message).
    """
    if not owner or not owner.printer_ip:
        return False, 'No has configurado la IP de tu impresora en Perfil del negocio.'

    width_chars = 32 if owner.printer_width_mm == 58 else 42

    try:
        printer = Network(owner.printer_ip, timeout=5)

        printer.set(align='center', bold=True, width=2, height=2)
        # print_order_ticket() (the route calling this) already blocks anything but
        # status == 'Confirmed', so daily_number is always set here.
        printer.text(f'ORDEN #{order.daily_number}\n')
        printer.set(align='center', bold=False, width=1, height=1)
        printer.text('-' * width_chars + '\n')

        if order.delivery_mode == 'envio' and order.latitude is not None and order.longitude is not None:
            maps_url = f'https://www.google.com/maps/search/?api=1&query={order.latitude},{order.longitude}'
            printer.qr(maps_url, size=6, center=True)
            printer.text('\n')

        printer.set(align='left', bold=False)
        printer.text(f'Cliente: {order.customer_name}\n')
        printer.text(f'Tel: {order.phone}\n')
        printer.text(f'Hora: {order.requested_time_label}\n')
        if order.delivery_mode == 'envio' and order.address:
            printer.text(f'Dir: {order.address}\n')
        printer.text('-' * width_chars + '\n')

        for item in order.order_items:
            product_name = item.product_name
            # Plain text, no emoji - thermal printers' code pages can't print it.
            gift_text = ' (regalo)' if item.is_gift else ''
            printer.text(f'{item.quantity}x {product_name}{gift_text}\n')
            for option in item.selected_options:
                printer.text(f'   + {option.name}\n')
        if order.notes:
            printer.text(f'Nota: {order.notes}\n')
        printer.text('-' * width_chars + '\n')

        printer.set(align='center', bold=True)
        method_label = {'efectivo': 'EFECTIVO', 'transferencia': 'TRANSFERENCIA', 'tarjeta': 'TARJETA'}.get(order.payment_method)
        if method_label:
            printer.text(f'{method_label}\n')
        printer.set(align='center', bold=False)
        # payment_status (not payment_method) decides pagado/no pagado - every method
        # is confirmed manually by the owner (A2.2.1), so a transferencia that hasn't
        # actually landed must print "cobrar", never "ya pagado" (the courier would
        # hand over the order for nothing). The method only decides HOW to collect
        # once we already know payment is still pending.
        if order.payment_status == 'paid':
            printer.text('YA PAGADO\n')
        else:
            printer.text('COBRAR EN LA ENTREGA\n')
            cash_summary = cash_payment_summary(order)
            if cash_summary is not None:
                printer.text(f'Paga con: ${order.cash_amount:.0f}\n')
                if cash_summary['status'] == 'over':
                    printer.text(f"Vuelto: ${cash_summary['amount']:.0f}\n")
                elif cash_summary['status'] == 'exact':
                    printer.text('Paga justo\n')
                else:
                    printer.text(f'OJO: dijo que pagaba con ${order.cash_amount:.0f} pero el total es '
                                  f"${order.total_price:.0f}\n")
                    printer.text(f"FALTAN ${cash_summary['amount']:.0f}\n")
            elif order.payment_method == 'tarjeta':
                printer.text('(llevar máquina)\n')
            elif order.payment_method == 'transferencia':
                printer.text('(pedir comprobante)\n')

        printer.set(align='center', bold=True)
        printer.text(f'\nTOTAL: ${order.total_price:.0f}\n\n')
        printer.cut()
        printer.close()
        return True, None
    except Exception as e:
        return False, f'No se pudo conectar con la impresora ({e}).'


ROUTE_STOP_NUMBERS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']


def _build_route_message(orders):
    """Combine several deliveries into one message, numbered in the order the
    driver should actually deliver them - by requested time, not by whatever
    order the owner happened to tick the checkboxes in."""
    sorted_orders = sorted(orders, key=lambda order: order.requested_time or '99:99')
    parts = [f'🛵 Recorrido de entregas - {len(sorted_orders)} pedidos, en este orden:']
    for index, order in enumerate(sorted_orders):
        stop_label = ROUTE_STOP_NUMBERS[index] if index < len(ROUTE_STOP_NUMBERS) else f'{index + 1}.'
        parts.append(f'\n{stop_label}\n{_build_courier_message(order)}')
    return '\n'.join(parts)


@catalog.route('/categories')
@login_required
@admin_required
def categories():
    all_categories = Category.query.order_by(Category.name).all()
    return render_template('panel/categories.html', categories=all_categories)


def _same_name(a, b):
    """Names the owner would read as the same: case and surrounding spaces don't count.
    casefold() in Python, not SQL lower() - SQLite's only folds ASCII ("Fríos"/"FRÍOS")."""
    return a.strip().casefold() == b.strip().casefold()


def _category_name_taken(name, exclude_id=None):
    return any(_same_name(category.name, name)
               for category in Category.query.filter(Category.id != exclude_id).all())


def _subcategory_name_taken(name, category_id, exclude_id=None):
    """Unique within its category only - "Fríos" can exist under Bebidas and Postres."""
    return any(_same_name(sub.name, name)
               for sub in Subcategory.query.filter(Subcategory.category_id == category_id,
                                                   Subcategory.id != exclude_id).all())


@catalog.route('/categories/new', methods=['POST'])
@login_required
@admin_required
def create_category():
    name = request.form.get('name', '').strip()
    if not name:
        flash('El nombre de la categoría es obligatorio.')
        return redirect(url_for('catalog.categories'))

    if _category_name_taken(name):
        flash('Ya existe una categoría con ese nombre.')
        return redirect(url_for('catalog.categories'))

    db.session.add(Category(name=name))
    try:
        db.session.commit()
    except IntegrityError:
        # Safety net for two simultaneous requests both passing the check above before
        # either commits - the UniqueConstraint is the real guarantee, this is just
        # keeping the failure a clean flash instead of a 500 page.
        db.session.rollback()
        flash('Ya existe una categoría con ese nombre.')
        return redirect(url_for('catalog.categories'))

    flash('Categoría creada')
    return redirect(url_for('catalog.categories'))


@catalog.route('/categories/<int:category_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_category(category_id):
    category = Category.query.get_or_404(category_id)
    if request.method == 'GET':
        return render_template('panel/category_form.html', category=category, name=category.name)

    name = request.form.get('name', '').strip()

    def _redisplay(message):
        flash(message)
        return render_template('panel/category_form.html', category=category, name=name)

    if not name:
        return _redisplay('El nombre de la categoría es obligatorio.')
    if len(name) > 50:
        return _redisplay('El nombre puede tener hasta 50 caracteres.')
    if _category_name_taken(name, exclude_id=category.id):
        return _redisplay('Ya existe una categoría con ese nombre.')

    category.name = name
    try:
        db.session.commit()
    except IntegrityError:
        # Same safety net as create_category: the UniqueConstraint is the real guarantee.
        db.session.rollback()
        return _redisplay('Ya existe una categoría con ese nombre.')

    flash('Categoría guardada')
    return redirect(url_for('catalog.categories'))


@catalog.route('/categories/<int:category_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    if category.subcategories:
        flash('Elimina primero las subcategorías de esta categoría.')
        return redirect(url_for('catalog.categories'))

    db.session.delete(category)
    db.session.commit()
    flash('Categoría eliminada')
    return redirect(url_for('catalog.categories'))


@catalog.route('/subcategories/new', methods=['POST'])
@login_required
@admin_required
def create_subcategory():
    name = request.form.get('name', '').strip()
    category_id = request.form.get('category_id', type=int)
    category = Category.query.get(category_id) if category_id else None

    if not name or category is None:
        flash('Completa el nombre y la categoría de la subcategoría.')
        return redirect(url_for('catalog.categories'))

    if _subcategory_name_taken(name, category.id):
        flash('Ya existe una subcategoría con ese nombre en esta categoría.')
        return redirect(url_for('catalog.categories'))

    db.session.add(Subcategory(name=name, category_id=category.id))
    try:
        db.session.commit()
    except IntegrityError:
        # Same safety net as create_category - the UniqueConstraint on
        # (name, category_id) is the real guarantee against a race between two
        # simultaneous requests.
        db.session.rollback()
        flash('Ya existe una subcategoría con ese nombre en esta categoría.')
        return redirect(url_for('catalog.categories'))

    flash('Subcategoría creada')
    return redirect(url_for('catalog.categories'))


def _subcategory_form(subcategory, name, description, category_id):
    return render_template('panel/subcategory_form.html', subcategory=subcategory,
                           categories=Category.query.order_by(Category.name).all(),
                           name=name, description=description, category_id=category_id,
                           product_count=len(subcategory.products))


@catalog.route('/subcategories/<int:subcategory_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_subcategory(subcategory_id):
    """Name, description and the category it belongs to. Moving it to another category
    moves its products along in the same commit - a product's category_id and its
    subcategory's category must never disagree (the menu groups by one, the panel by
    the other)."""
    subcategory = Subcategory.query.get_or_404(subcategory_id)
    if request.method == 'GET':
        return _subcategory_form(subcategory, subcategory.name, subcategory.description or '',
                                 subcategory.category_id)

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    category_id = request.form.get('category_id', type=int)
    category = Category.query.get(category_id) if category_id else None

    def _redisplay(message):
        flash(message)
        return _subcategory_form(subcategory, name, description, category_id)

    if not name or category is None:
        return _redisplay('Completa el nombre y la categoría de la subcategoría.')
    if len(name) > 50:
        return _redisplay('El nombre puede tener hasta 50 caracteres.')
    # The input's maxlength is only a hint - SQLite doesn't enforce String(200) either.
    if len(description) > 200:
        return _redisplay('La descripción puede tener hasta 200 caracteres.')
    if _subcategory_name_taken(name, category.id, exclude_id=subcategory.id):
        return _redisplay(f'Ya existe una subcategoría con ese nombre en {category.name}.')

    moved = category.id != subcategory.category_id
    subcategory.name = name
    subcategory.description = description or None  # empty = remove it
    subcategory.category_id = category.id
    if moved:
        for product in subcategory.products:
            product.category_id = category.id
    try:
        db.session.commit()
    except IntegrityError:
        # Same safety net as create_subcategory: unique (name, category_id) is the real guarantee.
        db.session.rollback()
        return _redisplay(f'Ya existe una subcategoría con ese nombre en {category.name}.')

    if moved and subcategory.products:
        count = len(subcategory.products)
        flash(f'Subcategoría guardada y movida a {category.name}, con '
              f'{count} producto{"s" if count != 1 else ""}.')
    else:
        flash('Subcategoría guardada')
    return redirect(url_for('catalog.categories'))


@catalog.route('/subcategories/<int:subcategory_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_subcategory(subcategory_id):
    subcategory = Subcategory.query.get_or_404(subcategory_id)
    if subcategory.products:
        flash('Elimina o reasigna primero los productos de esta subcategoría.')
        return redirect(url_for('catalog.categories'))

    db.session.delete(subcategory)
    db.session.commit()
    flash('Subcategoría eliminada')
    return redirect(url_for('catalog.categories'))


@catalog.route('/products')
@login_required
@admin_required
def products():
    all_products = Product.query.order_by(Product.category_id, Product.name).all()
    return render_template('panel/products.html', products=all_products)


def _product_form_context(product=None, posted_tiers=None):
    """posted_tiers: the quantity-pricing fields as the owner sent them ({'rows', 'enabled',
    'featured'}), when the form comes back with an error - so they aren't lost.
    Otherwise the saved state is shown."""
    tiered_promo = _own_tiered_promo(product) if product else None
    if posted_tiers is not None:
        tier_rows = posted_tiers['rows']
        tiered_enabled = posted_tiers['enabled']
        featured_quantity = posted_tiers['featured']
    else:
        tier_rows = [(tier.quantity, tier.total_price) for tier in tiered_promo.tiers] if tiered_promo else []
        tiered_enabled = bool(tiered_promo and tiered_promo.is_active)
        featured_quantity = tiered_promo.featured_quantity if tiered_promo else 1
    return {
        'product': product,
        'categories': Category.query.order_by(Category.name).all(),
        'subcategories': Subcategory.query.order_by(Subcategory.name).all(),
        'tiered_promo': tiered_promo,
        'legacy_tiered_promos': _legacy_tiered_promos(product) if product else [],
        'can_edit_tiers': current_user.is_owner,
        'tiered_enabled': tiered_enabled,
        'tier_rows': tier_rows + [(None, None)] * _TIER_FORM_EXTRA_ROWS,
        # The saving is only shown next to saved tiers - typed ones haven't been validated.
        'tiers_saved': posted_tiers is None,
        'featured_quantity': featured_quantity,
        'featured_choices': _featured_choices(tier_rows),
        'pack_like_group_ids': ({group.id for group in _pack_like_option_groups(product)}
                                if tiered_promo and tiered_promo.is_active else set()),
    }


def _featured_choices(tier_rows):
    """The tiers the "precio que se destaca" select offers: rows with a usable quantity
    and price, as (quantity, total_price). Rows may be typed strings (a form that came
    back with an error) - unusable ones are just left out of the select."""
    choices = []
    for quantity, total_price in tier_rows:
        try:
            quantity, total_price = int(quantity), int(float(total_price))
        except (TypeError, ValueError):
            continue
        if quantity >= 2 and quantity not in {q for q, _price in choices}:
            choices.append((quantity, total_price))
    return sorted(choices)


# An option named like an amount ("3 unidades", "x6", "X 12") - with a surcharge, that's
# a hand-made pack, which quantity pricing replaces.
_QUANTITY_LIKE_OPTION = re.compile(r'^\s*(\d|x\s*\d)', re.IGNORECASE)


def _pack_like_option_groups(product):
    """Option groups that look like the old way of selling packs: a paid option whose
    name starts with a number or "x<number>". Alongside quantity pricing they charge
    twice for the same thing - the editor warns, without blocking."""
    return [group for group in product.option_groups
            if any(option.price_delta > 0 and _QUANTITY_LIKE_OPTION.match(option.name) for option in group.options)]


def _own_tiered_promo(product):
    """The product's quantity pricing ("2 por $4.990"): the tiered promo holding only
    this product. Tiered promos are configured from the product editor, one each."""
    return next((promo for promo in product.bundle_promos
                 if promo.kind == 'tiered' and len(promo.products) == 1), None)


def _legacy_tiered_promos(product):
    """Tiered promos shared with other products - only possible from before quantity
    pricing moved to the product editor. Shown read-only; removed from Promociones."""
    return [promo for promo in product.bundle_promos if promo.kind == 'tiered' and len(promo.products) > 1]


def _tiered_label(product_name):
    """Shown to the customer (cart breakdown, WhatsApp message), so it reads as a phrase."""
    return f'Precio por cantidad - {product_name}'[:80]


def _first_tier_without_saving(base_price, tiers):
    """The first (quantity, total_price) that doesn't cost less than buying `quantity`
    singles at base_price, or None if every tier is a real discount."""
    return next(((quantity, total_price) for quantity, total_price in tiers
                 if total_price >= quantity * base_price), None)


def _tiered_overlap_error(product_name, product, own_promo):
    """A product may be in only ONE active automatic promo. Its quantity pricing counts
    from today on, forever - so any other active promo conflicts unless it already
    ended (a 2x1 whose valid_until is past, still switched on)."""
    today = datetime.now(BUSINESS_TZ).date()
    for other in product.bundle_promos:
        if other is own_promo or not other.is_active:
            continue
        if not _dates_overlap(today, None, other.valid_from, other.valid_until):
            continue
        return (f'"{product_name}" ya está en la promo "{other.label}". Un producto solo puede tener '
                'una promo activa: quítalo de esa promo primero.')
    return None


def _resolve_featured_quantity(raw, tiers, own_promo):
    """(featured_quantity, error, note) for the "precio que se destaca" select. 1 (the
    single price) or one of `tiers`' quantities. A quantity that was a saved tier but
    isn't anymore means the owner just deleted the featured tier: back to 1, with a note."""
    if raw in (None, ''):
        return 1, None, None
    try:
        featured = int(raw)
    except ValueError:
        featured = None
    if featured == 1 or featured in {quantity for quantity, _price in tiers}:
        return featured, None, None
    if featured is not None and own_promo and featured in {tier.quantity for tier in own_promo.tiers}:
        return 1, None, (f'Quitaste el nivel de {featured}, que era el destacado: la carta vuelve a '
                         'destacar el precio suelto.')
    return None, 'El precio que se destaca en la carta debe ser "Suelto" o uno de los niveles.', None


def _apply_product_tiers(product, promo, tiers, featured_quantity):
    """Create or update the product's own tiered promo, switched on, to match `tiers`
    (already validated, never empty). Switching it off is just is_active=False."""
    if promo is None:
        promo = BundlePromo(kind='tiered')
        db.session.add(promo)
    promo.label = _tiered_label(product.name)
    promo.buy_quantity = promo.pay_quantity = None
    # Always permanent and active: the product editor is the only place it's managed.
    promo.valid_from = promo.valid_until = None
    promo.is_active = True
    promo.featured_quantity = featured_quantity
    promo.products = [product]
    # Old tiers must be gone before the new ones go in: SQLAlchemy inserts before it
    # deletes within one flush, which would trip unique(promo_id, quantity) whenever
    # an edit keeps a quantity (the usual case - e.g. only changing a price).
    promo.tiers.clear()
    db.session.flush()
    promo.tiers = [BundlePromoTier(quantity=quantity, total_price=total_price)
                   for quantity, total_price in tiers]


@catalog.route('/products/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_product():
    if request.method == 'POST':
        return _save_product(Product())
    return render_template('panel/product_form.html', **_product_form_context())


@catalog.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        return _save_product(product)
    return render_template('panel/product_form.html', **_product_form_context(product))


def _save_product(product):
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    price = parse_money(request.form, 'price')
    original_price = parse_money(request.form, 'original_price')
    category_id = request.form.get('category_id', type=int)
    subcategory_id = request.form.get('subcategory_id', type=int) or None

    category = Category.query.get(category_id) if category_id else None
    subcategory = Subcategory.query.get(subcategory_id) if subcategory_id else None
    if subcategory and subcategory.category_id != category_id:
        subcategory = None

    # The quantity-pricing fields as sent - the form comes back with them if anything fails.
    posted_tiers = {
        'rows': [(quantity, total_price) for quantity, total_price
                 in zip(request.form.getlist('tier_quantity'), request.form.getlist('tier_price'))
                 if quantity.strip() or total_price.strip()],
        'enabled': request.form.get('tiered_enabled') == 'on',
        'featured': request.form.get('featured_quantity', 1, type=int),
    }

    def _redisplay():
        return render_template('panel/product_form.html',
                               **_product_form_context(product if product.id else None, posted_tiers))

    if not name or not description or price is None or category is None:
        flash('Completa nombre, descripción, precio y categoría del producto.')
        return _redisplay()

    # Quantity pricing. Only the owner sets it (like every promo), and only when the form
    # sent its fields at all - a POST without them leaves it as it is.
    #   tiered_action None: untouched / 'off': switched off, tiers kept / 'on': save `tiers`.
    own_promo = _own_tiered_promo(product) if product.id else None
    tiered_action, tiers, featured_quantity, featured_note = None, [], 1, None
    if current_user.is_owner and 'tier_quantity' in request.form and not _legacy_tiered_promos(product):
        if not posted_tiers['enabled']:
            tiered_action = 'off'
        else:
            tiered_action = 'on'
            tiers, error = _parse_tiers(request.form)
            if not error:
                error = _tiered_overlap_error(name, product, own_promo)
            if not error:
                featured_quantity, error, featured_note = _resolve_featured_quantity(
                    request.form.get('featured_quantity'), tiers, own_promo)
            if error:
                flash(error)
                return _redisplay()

    # Validated against the price being saved now, edited or not: a cheaper product can
    # turn a tier that will apply into no discount at all, and staff can change the price
    # too. Tiers switched off don't apply, so they're checked when switched back on.
    if tiered_action == 'on':
        tiers_to_check = tiers
    elif tiered_action is None and own_promo and own_promo.is_active:
        tiers_to_check = [(tier.quantity, tier.total_price) for tier in own_promo.tiers]
    else:
        tiers_to_check = []
    bad_tier = _first_tier_without_saving(price, tiers_to_check)
    if bad_tier:
        quantity, total_price = bad_tier
        message = (f'Precio por cantidad: el nivel de {quantity} (${total_price:.0f}) debe costar menos de '
                   f'${quantity * price:.0f} ({quantity} × ${price:.0f}), si no, no es un descuento.')
        if not current_user.is_owner:
            message += ' Pídele al dueño que ajuste el precio por cantidad, o deja el precio como estaba.'
        flash(message)
        return _redisplay()

    is_new = product.id is None
    product.name = name
    product.description = description
    product.price = price
    # Only keep it when it actually represents a discount (higher than the current price) -
    # otherwise there's nothing to show struck-through on the public menu.
    product.original_price = original_price if original_price and original_price > price else None
    product.category_id = category.id
    product.subcategory_id = subcategory.id if subcategory else None
    product.stock_quantity = request.form.get('stock_quantity', type=int)
    if product.stock_quantity is not None:
        product.sold_out = product.stock_quantity <= 0
    prep_minutes = request.form.get('prep_minutes', type=int)
    # Purely informational field - 0, negative or non-numeric input never blocks
    # saving the product, it just means no prep time is shown to the customer.
    product.prep_minutes = prep_minutes if prep_minutes and prep_minutes > 0 else None
    # An unchecked checkbox isn't sent at all - False is right because this form always
    # renders it. Any other POST to _save_product without the field would switch it off.
    product.suggest_in_cart = request.form.get('suggest_in_cart') == 'on'
    if is_new:
        product.is_active = True

    db.session.add(product)
    db.session.flush()  # assigns product.id for a stable image filename

    image = request.files.get('image')
    if image and image.filename:
        new_filename = save_image(
            existing_filename=product.image_filename,
            file_storage=image,
            upload_dir=current_app.config['PRODUCT_UPLOAD_DIR'],
            filename_stub=f'product_{product.id}',
            allowed_extensions=current_app.config['PRODUCT_ALLOWED_EXTENSIONS'],
        )
        if new_filename is None:
            db.session.rollback()
            flash('La foto del producto debe ser una imagen (png, jpg, jpeg o webp).')
            return render_template('panel/product_form.html',
                                   **_product_form_context(product if not is_new else None, posted_tiers))
        product.image_filename = new_filename

    if tiered_action == 'on':
        _apply_product_tiers(product, own_promo, tiers, featured_quantity)
    elif tiered_action == 'off' and own_promo:
        # Off keeps the tiers and the featured choice - switching back on restores them.
        own_promo.is_active = False
        own_promo.label = _tiered_label(product.name)

    db.session.commit()
    flash('Producto guardado')
    if featured_note:
        flash(featured_note)
    # Saved anyway - the owner may be repricing a whole promo one product at a time - but
    # say so: a tiered promo whose products don't share one price stops applying.
    for promo in product.bundle_promos:
        if promo.is_active and promo.price_mismatch:
            flash(f'Este producto está en la promo "{promo.label}"; con este precio la promo '
                  'dejará de aplicarse hasta que todos sus productos tengan el mismo precio.')
    return redirect(url_for('catalog.products'))


def _join_with_y(items):
    """'a' / 'a y b' / 'a, b y c' - Spanish list joining for the delete_product() flash."""
    if len(items) <= 1:
        return items[0] if items else ''
    return ', '.join(items[:-1]) + ' y ' + items[-1]


def _product_delete_blockers(product):
    """Every reason product can't be deleted right now - product.orders isn't the
    only thing that silently breaks if a product referenced elsewhere just
    disappears: a coupon/bundle promo built around it stops discounting anything,
    and a gift product vanishes from the threshold banner, without telling anyone."""
    reasons = []
    if product.orders:
        reasons.append('tiene pedidos asociados')
    if product.coupons:
        codes = _join_with_y([f"'{c.code}'" for c in product.coupons])
        word = 'cupón' if len(product.coupons) == 1 else 'cupones'
        reasons.append(f'está en el {word} {codes}')
    # Its own quantity pricing isn't a blocker: it only exists for this product, so it
    # goes with it (see delete_product).
    own_promo = _own_tiered_promo(product)
    other_promos = [promo for promo in product.bundle_promos if promo is not own_promo]
    if other_promos:
        labels = _join_with_y([f"'{p.label}'" for p in other_promos])
        article, word = ('la', 'promo') if len(other_promos) == 1 else ('las', 'promos')
        reasons.append(f'está en {article} {word} {labels}')
    if User.query.filter_by(gift_product_id=product.id).first():
        reasons.append('es el regalo configurado por compra mínima')
    if product.gift_coupons:
        codes = _join_with_y([f"'{c.code}'" for c in product.gift_coupons])
        word = 'del cupón' if len(product.gift_coupons) == 1 else 'de los cupones'
        reasons.append(f'es el producto de regalo {word} {codes}')
    return reasons


@catalog.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    reasons = _product_delete_blockers(product)
    if reasons:
        flash('No se puede eliminar: ' + _join_with_y(reasons) +
              '. Quítalo de esas promociones primero, o desactívalo.')
        return redirect(url_for('catalog.products'))

    own_promo = _own_tiered_promo(product)
    if own_promo:
        db.session.delete(own_promo)
        db.session.flush()
        # The association row went with the promo - forget the stale collection so
        # deleting the product doesn't try to remove that row a second time.
        db.session.expire(product, ['bundle_promos'])
    db.session.delete(product)
    db.session.commit()
    flash('Producto eliminado')
    return redirect(url_for('catalog.products'))


@catalog.route('/products/<int:product_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_product_active(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_active = not product.is_active
    db.session.commit()
    flash('Producto activado' if product.is_active else 'Producto desactivado')
    return redirect(url_for('catalog.products'))


@catalog.route('/products/<int:product_id>/toggle-sold-out', methods=['POST'])
@login_required
@admin_required
def toggle_product_sold_out(product_id):
    product = Product.query.get_or_404(product_id)
    product.sold_out = not product.sold_out
    db.session.commit()
    flash('Producto marcado como agotado' if product.sold_out else 'Producto marcado como disponible')
    return redirect(url_for('catalog.products'))


@catalog.route('/products/<int:product_id>/toggle-featured', methods=['POST'])
@login_required
@admin_required
def toggle_product_featured(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_featured = not product.is_featured
    db.session.commit()
    flash('Producto marcado como recomendado' if product.is_featured else 'Producto ya no es recomendado')
    return redirect(url_for('catalog.products'))


def _parse_group_select_limits(form, multi_select):
    """min_select/max_select solo aplican a grupos multi_select - en single-select el tope
    ya lo da required/el propio radio, así que cualquier valor mandado se ignora (NULL).
    Devuelve (min_select, max_select, error_message)."""
    if not multi_select:
        return None, None, None
    min_select = form.get('min_select', type=int)
    max_select = form.get('max_select', type=int)
    min_select = min_select if min_select and min_select > 0 else None
    max_select = max_select if max_select and max_select > 0 else None
    if min_select is not None and max_select is not None and max_select < min_select:
        return None, None, 'El máximo no puede ser menor que el mínimo.'
    return min_select, max_select, None


@catalog.route('/products/<int:product_id>/option-groups/new', methods=['POST'])
@login_required
@admin_required
def create_option_group(product_id):
    product = Product.query.get_or_404(product_id)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Ponle un nombre al grupo de variantes (ej. "Tamaño", "Extras").')
        return redirect(url_for('catalog.edit_product', product_id=product.id))

    multi_select = 'multi_select' in request.form
    min_select, max_select, error = _parse_group_select_limits(request.form, multi_select)
    if error:
        flash(error)
        return redirect(url_for('catalog.edit_product', product_id=product.id))

    db.session.add(ProductOptionGroup(
        product_id=product.id,
        name=name,
        required='required' in request.form,
        multi_select=multi_select,
        min_select=min_select,
        max_select=max_select,
    ))
    db.session.commit()
    flash('Grupo de variantes agregado')
    return redirect(url_for('catalog.edit_product', product_id=product.id))


@catalog.route('/products/<int:product_id>/option-groups/<int:group_id>/edit', methods=['POST'])
@login_required
@admin_required
def update_option_group(product_id, group_id):
    group = ProductOptionGroup.query.filter_by(id=group_id, product_id=product_id).first_or_404()
    name = request.form.get('name', '').strip()
    if not name:
        flash('Ponle un nombre al grupo de variantes (ej. "Tamaño", "Extras").')
        return redirect(url_for('catalog.edit_product', product_id=product_id))

    multi_select = 'multi_select' in request.form
    min_select, max_select, error = _parse_group_select_limits(request.form, multi_select)
    if error:
        flash(error)
        return redirect(url_for('catalog.edit_product', product_id=product_id))

    group.name = name
    group.required = 'required' in request.form
    group.multi_select = multi_select
    group.min_select = min_select
    group.max_select = max_select

    # Bajar de multi-select a single-select convierte los checkbox en radio - si quedaba
    # más de una opción marcada como default, el navegador solo respetaría la última de
    # todas formas. Misma resolución que ya hace create_option: se deja solo una.
    if not multi_select:
        defaults = ProductOption.query.filter_by(group_id=group.id, is_default=True) \
            .order_by(ProductOption.id).all()
        for option in defaults[1:]:
            option.is_default = False

    db.session.commit()
    flash('Grupo de variantes actualizado')
    return redirect(url_for('catalog.edit_product', product_id=product_id))


@catalog.route('/products/<int:product_id>/option-groups/<int:group_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_option_group(product_id, group_id):
    group = ProductOptionGroup.query.filter_by(id=group_id, product_id=product_id).first_or_404()
    db.session.delete(group)
    db.session.commit()
    flash('Grupo de variantes eliminado')
    return redirect(url_for('catalog.edit_product', product_id=product_id))


@catalog.route('/products/<int:product_id>/option-groups/<int:group_id>/options/new', methods=['POST'])
@login_required
@admin_required
def create_option(product_id, group_id):
    group = ProductOptionGroup.query.filter_by(id=group_id, product_id=product_id).first_or_404()
    name = request.form.get('name', '').strip()
    price_delta = parse_money(request.form, 'price_delta')
    if not name or price_delta is None:
        flash('Completa el nombre y el precio adicional de la opción (puede ser 0).')
        return redirect(url_for('catalog.edit_product', product_id=product_id))

    is_default = 'is_default' in request.form
    if is_default and not group.multi_select:
        ProductOption.query.filter_by(group_id=group.id, is_default=True).update({'is_default': False})

    db.session.add(ProductOption(group_id=group.id, name=name, price_delta=price_delta, is_default=is_default))
    db.session.commit()
    flash('Opción agregada')
    return redirect(url_for('catalog.edit_product', product_id=product_id))


@catalog.route('/products/<int:product_id>/option-groups/<int:group_id>/options/<int:option_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_option(product_id, group_id, option_id):
    option = ProductOption.query.filter_by(id=option_id, group_id=group_id).first_or_404()
    db.session.delete(option)
    db.session.commit()
    flash('Opción eliminada')
    return redirect(url_for('catalog.edit_product', product_id=product_id))


@catalog.route('/delivery')
@login_required
@owner_required
def delivery():
    tiers = DeliveryRadiusTier.query.order_by(DeliveryRadiusTier.min_km).all()
    zones = DeliveryZone.query.order_by(DeliveryZone.id).all()
    zones_geojson = json.dumps([json.loads(zone.geojson) for zone in zones])
    return render_template('panel/delivery.html', tiers=tiers, zones=zones, zones_geojson=zones_geojson)


@catalog.route('/delivery/tiers/new', methods=['POST'])
@login_required
@owner_required
def create_delivery_tier():
    min_km = request.form.get('min_km', type=float)
    max_km = request.form.get('max_km', type=float)
    price = parse_money(request.form, 'price')

    if min_km is None or max_km is None or price is None or min_km >= max_km or min_km < 0:
        flash('Revisa los kilómetros y el precio del rango de reparto.')
        return redirect(url_for('catalog.delivery'))

    db.session.add(DeliveryRadiusTier(min_km=min_km, max_km=max_km, price=price))
    db.session.commit()
    flash('Rango de reparto agregado')
    return redirect(url_for('catalog.delivery'))


@catalog.route('/delivery/tiers/<int:tier_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_delivery_tier(tier_id):
    tier = DeliveryRadiusTier.query.get_or_404(tier_id)
    db.session.delete(tier)
    db.session.commit()
    flash('Rango de reparto eliminado')
    return redirect(url_for('catalog.delivery'))


@catalog.route('/delivery/zones/new', methods=['POST'])
@login_required
@owner_required
def create_delivery_zone():
    name = request.form.get('name', '').strip()
    price = parse_money(request.form, 'price')
    geojson_raw = request.form.get('geojson', '')

    if not name or price is None or not geojson_raw:
        flash('Dibuja el área en el mapa y completa nombre y precio.')
        return redirect(url_for('catalog.delivery'))

    try:
        shape(json.loads(geojson_raw))
    except (ValueError, TypeError):
        flash('El área dibujada no es válida, intenta de nuevo.')
        return redirect(url_for('catalog.delivery'))

    db.session.add(DeliveryZone(name=name, price=price, geojson=geojson_raw))
    db.session.commit()
    flash('Área de reparto agregada')
    return redirect(url_for('catalog.delivery'))


@catalog.route('/delivery/zones/<int:zone_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_delivery_zone(zone_id):
    zone = DeliveryZone.query.get_or_404(zone_id)
    db.session.delete(zone)
    db.session.commit()
    flash('Área de reparto eliminada')
    return redirect(url_for('catalog.delivery'))


@catalog.route('/promotions')
@login_required
@owner_required
def promotions():
    active_coupons = Coupon.query.filter_by(is_active=True).count()
    active_bundle_promos = BundlePromo.query.filter(BundlePromo.is_active.is_(True), BundlePromo.kind != 'tiered').count()
    products = Product.query.order_by(Product.name).all()
    return render_template('panel/promotions.html', active_coupons=active_coupons,
                            active_bundle_promos=active_bundle_promos, products=products)


@catalog.route('/promotions/gift', methods=['POST'])
@login_required
@owner_required
def update_gift_promo():
    threshold = parse_money(request.form, 'gift_threshold_amount')
    product_id = request.form.get('gift_product_id', type=int) or None

    if bool(threshold) != bool(product_id):
        flash('Para activar el regalo por compra mínima, completa el monto y elige un producto - '
              'o deja ambos vacíos para desactivarlo.')
        return redirect(url_for('catalog.promotions'))

    current_user.gift_threshold_amount = threshold
    current_user.gift_product_id = product_id
    db.session.commit()
    flash('Regalo por compra mínima actualizado')
    return redirect(url_for('catalog.promotions'))


@catalog.route('/coupons')
@login_required
@owner_required
def coupons():
    all_coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
    return render_template('panel/coupons.html', coupons=all_coupons)


def _coupon_form_context(coupon=None):
    return {
        'coupon': coupon,
        'products': Product.query.order_by(Product.name).all(),
        'selected_product_ids': {product.id for product in coupon.products} if coupon else set(),
    }


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


@catalog.route('/coupons/new', methods=['GET', 'POST'])
@login_required
@owner_required
def create_coupon():
    if request.method == 'POST':
        return _save_coupon(Coupon())
    return render_template('panel/coupon_form.html', **_coupon_form_context())


@catalog.route('/coupons/<int:coupon_id>/edit', methods=['GET', 'POST'])
@login_required
@owner_required
def edit_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    if request.method == 'POST':
        return _save_coupon(coupon)
    return render_template('panel/coupon_form.html', **_coupon_form_context(coupon))


def _save_coupon(coupon):
    code = request.form.get('code', '').strip().upper()
    kind = request.form.get('kind') or 'percent'
    discount_percent = request.form.get('discount_percent', type=float)
    fixed_amount = parse_money(request.form, 'fixed_amount')
    scope = request.form.get('scope')
    max_total_uses = request.form.get('max_total_uses', type=int)
    max_uses_per_customer = request.form.get('max_uses_per_customer', type=int)
    valid_from = _parse_date(request.form.get('valid_from'))
    valid_until = _parse_date(request.form.get('valid_until'))
    product_ids = request.form.getlist('product_ids', type=int)
    show_in_banner = request.form.get('show_in_banner') == 'on'
    applies_to_shipping = request.form.get('applies_to_shipping') == 'on'
    min_order_amount = parse_money(request.form, 'min_order_amount')
    gift_product_id = request.form.get('gift_product_id', type=int)

    if kind == 'product':
        # A gift isn't a discount on anything: scope/shipping/products don't apply (the
        # form disables them, so scope doesn't even arrive) - pinned to neutral values.
        scope, applies_to_shipping, product_ids = 'order', False, []

    def _redisplay():
        return render_template('panel/coupon_form.html', **_coupon_form_context(coupon if coupon.id else None))

    if not code or kind not in ('percent', 'fixed', 'product') or scope not in ('order', 'products'):
        flash('Completa el código, el tipo de cupón y a qué aplica.')
        return _redisplay()

    if kind == 'percent' and (discount_percent is None or not (0 < discount_percent <= 100)):
        flash('Ingresa un % de descuento válido (1-100).')
        return _redisplay()

    if kind == 'fixed' and (fixed_amount is None or fixed_amount <= 0):
        flash('Ingresa un monto de descuento mayor a 0.')
        return _redisplay()

    gift_product = Product.query.get(gift_product_id) if kind == 'product' and gift_product_id else None
    if kind == 'product' and gift_product is None:
        flash('Elige el producto que regala el cupón.')
        return _redisplay()

    if scope == 'products' and not product_ids:
        flash('Elige al menos un producto para un cupón de tipo "productos específicos".')
        return _redisplay()

    duplicate = Coupon.query.filter(db.func.upper(Coupon.code) == code, Coupon.id != coupon.id).first()
    if duplicate:
        flash('Ya existe un cupón con ese código.')
        return _redisplay()

    if valid_from and valid_until and valid_from > valid_until:
        flash('La fecha "desde" no puede ser posterior a la fecha "hasta".')
        return _redisplay()

    # Empty means no minimum; anything typed must parse to a positive amount
    # (parse_money returns None for garbage too, which mustn't silently mean "none").
    if (request.form.get('min_order_amount') or '').strip() and (min_order_amount is None or min_order_amount <= 0):
        flash('La compra mínima debe ser un monto mayor a 0, o déjala vacía para no exigir mínimo.')
        return _redisplay()

    is_new = coupon.id is None
    coupon.code = code
    coupon.kind = kind
    # Only the value of its own kind is kept, so switching an existing coupon's kind
    # never leaves a stale % or amount behind.
    coupon.discount_percent = discount_percent if kind == 'percent' else None
    coupon.fixed_amount = fixed_amount if kind == 'fixed' else None
    coupon.gift_product = gift_product
    coupon.scope = scope
    coupon.max_total_uses = max_total_uses
    coupon.max_uses_per_customer = max_uses_per_customer
    coupon.valid_from = valid_from
    coupon.valid_until = valid_until
    coupon.products = Product.query.filter(Product.id.in_(product_ids)).all() if scope == 'products' else []
    coupon.show_in_banner = show_in_banner
    coupon.applies_to_shipping = applies_to_shipping
    coupon.min_order_amount = min_order_amount
    if is_new:
        coupon.is_active = True

    db.session.add(coupon)
    db.session.flush()  # assigns coupon.id for a stable image filename

    image = request.files.get('banner_image')
    if image and image.filename:
        new_filename = save_image(
            existing_filename=coupon.banner_image_filename,
            file_storage=image,
            upload_dir=current_app.config['COUPON_UPLOAD_DIR'],
            filename_stub=f'coupon_{coupon.id}',
            allowed_extensions=current_app.config['COUPON_ALLOWED_EXTENSIONS'],
        )
        if new_filename is None:
            db.session.rollback()
            flash('La imagen del banner debe ser una imagen (png, jpg, jpeg o webp).')
            return render_template('panel/coupon_form.html', **_coupon_form_context(coupon if not is_new else None))
        coupon.banner_image_filename = new_filename

    db.session.commit()
    flash('Cupón guardado')
    return redirect(url_for('catalog.coupons'))


@catalog.route('/coupons/<int:coupon_id>/toggle-active', methods=['POST'])
@login_required
@owner_required
def toggle_coupon_active(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.is_active = not coupon.is_active
    db.session.commit()
    flash('Cupón activado' if coupon.is_active else 'Cupón desactivado')
    return redirect(url_for('catalog.coupons'))


@catalog.route('/coupons/<int:coupon_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    db.session.delete(coupon)
    db.session.commit()
    flash('Cupón eliminado')
    return redirect(url_for('catalog.coupons'))


@catalog.route('/bundle-promos')
@login_required
@owner_required
def bundle_promos():
    all_promos = BundlePromo.query.order_by(BundlePromo.id.desc()).all()
    # Tiered promos are each product's quantity pricing, edited in the product editor -
    # here they're only a summary, so the owner still sees every automatic discount.
    tiered_promos = sorted((promo for promo in all_promos if promo.kind == 'tiered'),
                           key=lambda promo: [product.name for product in promo.products])
    return render_template('panel/bundle_promos.html',
                           promos=[promo for promo in all_promos if promo.kind != 'tiered'],
                           tiered_promos=tiered_promos,
                           overlaps=_active_promo_overlaps(all_promos))


def _active_promo_overlaps(promos):
    """{promo.id: [(product name, other promo label), ...]} for every product sitting in
    two active promos whose dates cross. Saving/activating already refuses that, but
    data from before the rule (or edited outside the panel) can still have it - and then
    both discounts add up, so the owner should see it. Marked on both promos."""
    overlaps = {}
    active = [promo for promo in promos if promo.is_active]
    for index, promo in enumerate(active):
        for other in active[index + 1:]:
            if not _dates_overlap(promo.valid_from, promo.valid_until, other.valid_from, other.valid_until):
                continue
            shared_ids = {product.id for product in promo.products} & {product.id for product in other.products}
            for product in sorted((p for p in promo.products if p.id in shared_ids), key=lambda p: p.name):
                overlaps.setdefault(promo.id, []).append((product.name, other.label))
                overlaps.setdefault(other.id, []).append((product.name, promo.label))
    return overlaps


def _bundle_promo_form_context(promo=None):
    return {
        'promo': promo,
        'products': Product.query.order_by(Product.name).all(),
        'selected_product_ids': {product.id for product in promo.products} if promo else set(),
    }


def _redirect_tiered_promo(promo):
    """A tiered promo is managed from its product's editor, never from Promociones."""
    if len(promo.products) == 1:
        return redirect(url_for('catalog.edit_product', product_id=promo.products[0].id))
    flash('Este precio por cantidad es antiguo y está compartido entre varios productos: ya no se edita. '
          'Elimínalo y configura el precio por cantidad en cada producto.')
    return redirect(url_for('catalog.bundle_promos'))


@catalog.route('/bundle-promos/new', methods=['GET', 'POST'])
@login_required
@owner_required
def create_bundle_promo():
    if request.method == 'POST':
        return _save_bundle_promo(BundlePromo())
    return render_template('panel/bundle_promo_form.html', **_bundle_promo_form_context())


@catalog.route('/bundle-promos/<int:promo_id>/edit', methods=['GET', 'POST'])
@login_required
@owner_required
def edit_bundle_promo(promo_id):
    promo = BundlePromo.query.get_or_404(promo_id)
    if promo.kind == 'tiered':
        return _redirect_tiered_promo(promo)
    if request.method == 'POST':
        return _save_bundle_promo(promo)
    return render_template('panel/bundle_promo_form.html', **_bundle_promo_form_context(promo))


# Blank tier rows in the product form beyond the saved ones, so levels can be added without JS.
_TIER_FORM_EXTRA_ROWS = 2


def _parse_tiers(form):
    """The tier rows of the form as [(quantity, total_price)], or (None, error). A row
    with both fields empty is just an unused row; half-filled rows are an error."""
    quantities = form.getlist('tier_quantity')
    prices = form.getlist('tier_price')
    tiers = []
    for raw_quantity, raw_price in zip(quantities, prices):
        raw_quantity, raw_price = raw_quantity.strip(), raw_price.strip()
        if not raw_quantity and not raw_price:
            continue
        try:
            quantity = int(raw_quantity)
        except ValueError:
            return None, 'Cada nivel necesita una cantidad (2 o más) y un precio total.'
        total_price = parse_money({'price': raw_price}, 'price')
        if quantity < 2 or total_price is None or total_price <= 0:
            return None, 'Cada nivel necesita una cantidad (2 o más) y un precio total mayor a $0.'
        tiers.append((quantity, total_price))

    if not tiers:
        return None, 'Agrega al menos un nivel (ej. 2 por $4.990), o apaga el precio por cantidad.'
    if len({quantity for quantity, _price in tiers}) != len(tiers):
        return None, 'No puedes repetir la misma cantidad en dos niveles.'
    return sorted(tiers), None


def _dates_overlap(from_a, until_a, from_b, until_b):
    """Two optional date ranges (None = open-ended on that side) share at least one day."""
    starts_before_b_ends = from_a is None or until_b is None or from_a <= until_b
    b_starts_before_a_ends = from_b is None or until_a is None or from_b <= until_a
    return starts_before_b_ends and b_starts_before_a_ends


def _promo_overlap_error(promo_id, products, valid_from, valid_until):
    """A product may be in only ONE active automatic promo (of any kind) for any given
    day - so the cart never has to decide between two promos for the same unit. None
    if that holds for these products and dates, else the message to show."""
    for product in products:
        for other in product.bundle_promos:
            if other.id == promo_id or not other.is_active:
                continue
            if _dates_overlap(valid_from, valid_until, other.valid_from, other.valid_until):
                return (f'"{product.name}" ya está en la promo "{other.label}", activa en fechas que se '
                        'cruzan con estas. Un producto puede estar en una sola promoción activa a la vez.')
    return None


def _save_bundle_promo(promo):
    """Promociones only creates and edits 2x1/3x2 (buy_pay) promos - quantity pricing
    (tiered) lives in the product editor. Whatever kind the form says, this is a buy_pay."""
    is_new = promo.id is None
    label = request.form.get('label', '').strip()
    valid_from = _parse_date(request.form.get('valid_from'))
    valid_until = _parse_date(request.form.get('valid_until'))
    product_ids = request.form.getlist('product_ids', type=int)

    def _redisplay():
        return render_template('panel/bundle_promo_form.html', **_bundle_promo_form_context(promo if promo.id else None))

    if not label:
        flash('Completa un nombre para la promoción.')
        return _redisplay()

    buy_quantity = request.form.get('buy_quantity', type=int)
    pay_quantity = request.form.get('pay_quantity', type=int)
    if (not buy_quantity or not pay_quantity
            or buy_quantity < 2 or pay_quantity < 1 or pay_quantity >= buy_quantity):
        flash('Completa una combinación válida (ej. "Lleva 2, paga 1" - paga siempre debe ser menor que lleva).')
        return _redisplay()

    if not product_ids:
        flash('Elige al menos un producto para esta promoción.')
        return _redisplay()
    products = Product.query.filter(Product.id.in_(product_ids)).all()

    if valid_from and valid_until and valid_from > valid_until:
        flash('La fecha "desde" no puede ser posterior a la fecha "hasta".')
        return _redisplay()

    # Only an active promo competes for its products - a new one starts active.
    if is_new or promo.is_active:
        error = _promo_overlap_error(promo.id, products, valid_from, valid_until)
        if error:
            flash(error)
            return _redisplay()

    promo.label = label
    promo.kind = 'buy_pay'
    promo.buy_quantity = buy_quantity
    promo.pay_quantity = pay_quantity
    promo.valid_from = valid_from
    promo.valid_until = valid_until
    promo.products = products
    if is_new:
        promo.is_active = True
    db.session.add(promo)
    db.session.commit()
    flash('Promoción guardada')
    return redirect(url_for('catalog.bundle_promos'))


@catalog.route('/bundle-promos/<int:promo_id>/toggle-active', methods=['POST'])
@login_required
@owner_required
def toggle_bundle_promo_active(promo_id):
    promo = BundlePromo.query.get_or_404(promo_id)
    if promo.kind == 'tiered':
        # Quantity pricing is on while the product has tiers - removing them turns it off.
        flash('El precio por cantidad se enciende o apaga desde el editor del producto.')
        return redirect(url_for('catalog.bundle_promos'))
    if not promo.is_active:
        # Activating is the other way into "two active promos on one product".
        error = _promo_overlap_error(promo.id, promo.products, promo.valid_from, promo.valid_until)
        if error:
            flash(error)
            return redirect(url_for('catalog.bundle_promos'))
    promo.is_active = not promo.is_active
    db.session.commit()
    flash('Promoción activada' if promo.is_active else 'Promoción desactivada')
    return redirect(url_for('catalog.bundle_promos'))


@catalog.route('/bundle-promos/<int:promo_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_bundle_promo(promo_id):
    promo = BundlePromo.query.get_or_404(promo_id)
    db.session.delete(promo)
    db.session.commit()
    flash('Promoción eliminada')
    return redirect(url_for('catalog.bundle_promos'))


def _onboarding_checklist_tasks():
    """Detected automatically from real data, never a manual checkbox - same principle
    as the rest of this app: a flag can go stale, the data it's asking about can't."""
    has_hours = db.session.query(
        BusinessHours.query.filter(BusinessHours.opens_at.isnot(None)).exists()
    ).scalar()
    has_category = db.session.query(Category.query.exists()).scalar()
    has_active_product = db.session.query(Product.query.filter_by(is_active=True).exists()).scalar()
    has_product_photo = db.session.query(
        Product.query.filter(Product.image_filename.isnot(None)).exists()
    ).scalar()
    owner = User.query.filter_by(is_owner=True).first()
    has_whatsapp = bool(owner and owner.whatsapp_number)

    return [
        {
            'title': 'Configura tu horario de atención',
            'help': 'Sin horario, el sistema no sabe cuándo puede recibir pedidos ni la Agenda puede armar los bloques del día.',
            'done': has_hours,
            'url': url_for('auth.admin_panel'),
            'cta': 'Configurar horario',
        },
        {
            'title': 'Crea tu primera categoría',
            'help': 'Los productos necesitan una categoría para poder ordenarse en tu carta.',
            'done': has_category,
            'url': url_for('catalog.categories'),
            'cta': 'Crear categoría',
        },
        {
            'title': 'Agrega tu primer producto',
            'help': 'Sin productos no hay nada que un cliente pueda pedir todavía.',
            'done': has_active_product,
            'url': url_for('catalog.create_product'),
            'cta': 'Agregar producto',
        },
        {
            'title': 'Súbele una foto a un producto',
            'help': 'Una carta con fotos vende más que una lista de nombres - es lo primero que ve el cliente.',
            'done': has_product_photo,
            'url': url_for('catalog.products'),
            'cta': 'Subir foto',
        },
        {
            'title': 'Configura tu WhatsApp',
            'help': 'Es el número al que llegan los pedidos - sin esto, el cliente no tiene cómo cerrar la compra.',
            'done': has_whatsapp,
            'url': url_for('auth.admin_panel'),
            'cta': 'Configurar WhatsApp',
        },
    ]


def _onboarding_checklist_context():
    """None means "don't show the card at all" - covers all three reasons at once:
    no owner yet, the owner already hid it, or every task is already done. The
    delivery-zone suggestion is deliberately kept OUT of the X-of-N count - a
    retiro-only business can never "complete" it and must never see it as required."""
    owner = User.query.filter_by(is_owner=True).first()
    if not owner or owner.onboarding_checklist_dismissed:
        return None
    tasks = _onboarding_checklist_tasks()
    done_count = sum(1 for task in tasks if task['done'])
    if done_count == len(tasks):
        return None
    return {
        'tasks': tasks,
        'done_count': done_count,
        'total': len(tasks),
        'progress_percent': round(done_count / len(tasks) * 100),
        'show_delivery_suggestion': not has_delivery_configured(),
    }


@catalog.route('/onboarding-checklist/dismiss', methods=['POST'])
@login_required
@admin_required
def dismiss_onboarding_checklist():
    owner = User.query.filter_by(is_owner=True).first()
    if owner:
        owner.onboarding_checklist_dismissed = True
        db.session.commit()
    return redirect(url_for('catalog.dashboard'))


@catalog.route('/dashboard')
@login_required
@admin_required
def dashboard():
    total_orders = Order.query.count()
    confirmed_orders = Order.query.filter_by(status='Confirmed').count()
    confirmation_rate = round(confirmed_orders / total_orders * 100) if total_orders else 0

    # "Quién me debe" is a close-of-day figure, not a lifetime one - a stale order
    # from weeks ago shouldn't inflate it forever. Scoped to today (Santiago time),
    # same day boundary orders() uses so this matches what the encargado sees in
    # today's order list. Anchored to confirmed_at (not created_at): an order that
    # came in yesterday but got confirmed and paid today is today's money. A row
    # with confirmed_at NULL (never confirmed) never matches, which is correct.
    today_start_utc, today_end_utc = day_range_utc(datetime.now(BUSINESS_TZ).date())
    confirmed_unpaid = Order.query.filter(
        Order.status == 'Confirmed', Order.payment_status == 'pending',
        Order.confirmed_at >= today_start_utc, Order.confirmed_at < today_end_utc,
    ).count()

    last_order_ids = db.session.query(func.max(Order.id)).group_by(Order.phone)
    customers = (
        Order.query.filter(Order.id.in_(last_order_ids))
        .order_by(Order.created_at.desc())
        .all()
    )
    order_counts = dict(db.session.query(Order.phone, func.count(Order.id)).group_by(Order.phone).all())
    owner = User.query.filter_by(is_owner=True).first()

    # Only counts confirmed orders - a pending order might never have actually closed
    # over WhatsApp, so counting it here would overstate what's really selling.
    top_products = (
        db.session.query(
            Product.name,
            func.sum(OrderItem.quantity).label('total_quantity'),
            func.sum(OrderItem.price * OrderItem.quantity).label('total_revenue'),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status == 'Confirmed', OrderItem.is_gift.is_(False))  # a gift isn't a sale
        .group_by(Product.id, Product.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(10)
        .all()
    )

    menu_url = url_for('main.index', _external=True)

    return render_template(
        'panel/dashboard.html',
        total_orders=total_orders,
        confirmed_orders=confirmed_orders,
        confirmation_rate=confirmation_rate,
        confirmed_unpaid=confirmed_unpaid,
        customers=customers,
        order_counts=order_counts,
        PAYMENT_METHOD_LABELS=PAYMENT_METHOD_LABELS,
        owner=owner,
        top_products=top_products,
        menu_url=menu_url,
        menu_share_url=f'https://wa.me/?text={quote(f"Mira nuestro menú: {menu_url}")}',
        onboarding_checklist=_onboarding_checklist_context(),
    )


@catalog.route('/menu-qr.png')
@login_required
@admin_required
def menu_qr():
    """QR code for the public menu link - for flyers, Instagram bio, WhatsApp Business, etc."""
    menu_url = url_for('main.index', _external=True)
    img = qrcode.make(menu_url, box_size=8, border=2)
    buf = BytesIO()
    img.save(buf, format='PNG')
    return Response(buf.getvalue(), mimetype='image/png')


@catalog.route('/toggle-closed', methods=['POST'])
@login_required
@admin_required
def toggle_closed():
    owner = User.query.filter_by(is_owner=True).first()
    if owner:
        owner.is_closed_temporarily = not owner.is_closed_temporarily
        db.session.commit()
        flash('Tienda cerrada temporalmente.' if owner.is_closed_temporarily else 'Tienda abierta de nuevo.')
    return redirect(url_for('catalog.dashboard'))


# Used when the business has no BusinessHours configured at all, or today is
# specifically marked closed but still has leftover confirmed orders to show -
# a broad window covering typical lunch+dinner hours for a food business.
AGENDA_DEFAULT_OPENS_AT = '09:00'
AGENDA_DEFAULT_CLOSES_AT = '22:00'

TIME_RE = re.compile(r'^\d{2}:\d{2}$')


def _parse_time_to_minutes(time_str):
    """"HH:MM" -> minutes since midnight, or None if missing/unparseable (old data,
    free-form leftovers, etc.) - never raises, the caller decides what to do with None."""
    if not time_str or not TIME_RE.match(time_str):
        return None
    hh, mm = (int(part) for part in time_str.split(':'))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    return hh * 60 + mm


def _format_minutes(total_minutes):
    hh, mm = divmod(total_minutes % 1440, 60)
    return f'{hh:02d}:{mm:02d}'


def _build_agenda_blocks(confirmed_orders, block_minutes, opens_at, closes_at, now_str):
    """Groups today's confirmed orders into fixed-size time blocks between opens_at
    and closes_at. Everything is done in "minutes since opens_at" so a range that
    crosses midnight (opens_at > closes_at) is handled the same way as a normal one -
    closes_at, and any order/now time in the early-morning TAIL of that range, gets
    +1440 to land in the following day's segment of the same timeline.

    Returns (blocks, unscheduled_orders): blocks is a list of dicts (start/end in
    "HH:MM", is_past, orders, unpaid_count), in chronological order. unscheduled_orders
    holds anything with no requested_time, an unparseable one, or one that falls
    outside [opens_at, closes_at) - nothing with status='Confirmed' is ever dropped."""
    opens_minutes = _parse_time_to_minutes(opens_at)
    closes_minutes_raw = _parse_time_to_minutes(closes_at)

    if opens_minutes == closes_minutes_raw:
        # apertura == cierre is a zero-minute window - invalid input, not a real
        # schedule. Building a grid for it would be either empty or (worse) a full
        # 24h of phantom blocks depending on how the wrap math below reads it.
        # Nothing gets placed anywhere, but every confirmed order still has to
        # surface - same "never silently dropped" rule as any other unscheduled case.
        unscheduled = sorted(confirmed_orders, key=lambda order: (order.requested_time is None, order.requested_time or ''))
        return [], unscheduled

    wraps = closes_minutes_raw <= opens_minutes
    closes_minutes = closes_minutes_raw + 1440 if wraps else closes_minutes_raw

    def _to_timeline(minutes):
        # Only the early-morning TAIL of a genuinely wrapping schedule belongs to
        # "later" on this timeline - a time before opens_at but NOT in that tail
        # (e.g. 12:21 in an 18:00-02:00 day, or ANY time before opens_at when
        # closes_at is exactly '00:00' and there's no tail at all) simply hasn't
        # happened yet today. Shifting it too would push it past every block and
        # make the whole day read as already over.
        return minutes + 1440 if (wraps and minutes < closes_minutes_raw) else minutes

    now_minutes = _to_timeline(_parse_time_to_minutes(now_str))

    blocks = []
    block_start = opens_minutes
    while block_start < closes_minutes:
        block_end = min(block_start + block_minutes, closes_minutes)
        blocks.append({'start': block_start, 'end': block_end, 'orders': []})
        block_start += block_minutes

    unscheduled_orders = []
    for order in confirmed_orders:
        order_minutes = _parse_time_to_minutes(order.requested_time)
        if order_minutes is None:
            unscheduled_orders.append(order)
            continue
        order_minutes = _to_timeline(order_minutes)
        if not (opens_minutes <= order_minutes < closes_minutes) or not blocks:
            unscheduled_orders.append(order)
            continue
        block_index = min((order_minutes - opens_minutes) // block_minutes, len(blocks) - 1)
        blocks[block_index]['orders'].append(order)

    for block in blocks:
        block['orders'].sort(key=lambda order: _parse_time_to_minutes(order.requested_time) or 0)
        block['unpaid_count'] = sum(1 for order in block['orders'] if order.payment_status == 'pending')
        block['is_past'] = block['end'] <= now_minutes
        block['label_start'] = _format_minutes(block['start'])
        block['label_end'] = _format_minutes(block['end'])

    unscheduled_orders.sort(key=lambda order: (order.requested_time is None, order.requested_time or ''))
    return blocks, unscheduled_orders


@catalog.route('/agenda')
@login_required
@admin_required
def agenda():
    """Read-only view of today's CONFIRMED orders, grouped into time blocks - the
    daily_number is the bridge back to orders() (still the only place to act on a
    pedido: confirm, cancel, edit, print, mark paid)."""
    start_utc, end_utc = day_range_utc(datetime.now(BUSINESS_TZ).date())
    # Eager-loaded because the template shows each order's items (product_name +
    # selected_options) on every card - without this, order.order_items and each
    # item.selected_options are lazy='select' (app/models.py), so N orders would
    # fire N+1 queries just to render the day. orders()/orders.html has the exact
    # same lazy-load shape and the exact same gap - not fixed here on purpose,
    # that's a separate view/commit.
    confirmed_orders = (Order.query
                        .options(selectinload(Order.order_items).selectinload(OrderItem.selected_options))
                        .filter(Order.created_at >= start_utc, Order.created_at < end_utc,
                                Order.status == 'Confirmed', Order.requested_for_tomorrow.isnot(True))
                        .all())

    owner = User.query.filter_by(is_owner=True).first()
    block_minutes = owner.agenda_block_minutes if owner else 10

    hours_today = get_hours_for_today()
    if hours_today is None or hours_today.is_closed:
        opens_at, closes_at = AGENDA_DEFAULT_OPENS_AT, AGENDA_DEFAULT_CLOSES_AT
    else:
        opens_at, closes_at = hours_today.opens_at, hours_today.closes_at

    schedule_warning = None
    if opens_at == closes_at:
        schedule_warning = ('El horario de hoy no está bien configurado (apertura = cierre). '
                             'Revísalo en Perfil del negocio.')

    now_str = datetime.now(BUSINESS_TZ).strftime('%H:%M')
    blocks, unscheduled_orders = _build_agenda_blocks(confirmed_orders, block_minutes, opens_at, closes_at, now_str)

    unpaid_count = sum(1 for order in confirmed_orders if order.payment_status == 'pending')

    return render_template('panel/agenda.html', today=datetime.now(BUSINESS_TZ).date(),
                            block_minutes=block_minutes, blocks=blocks, unscheduled_orders=unscheduled_orders,
                            confirmed_count=len(confirmed_orders), unpaid_count=unpaid_count,
                            schedule_warning=schedule_warning,
                            PAYMENT_METHOD_LABELS=PAYMENT_METHOD_LABELS, PAYMENT_STATUS_LABELS=PAYMENT_STATUS_LABELS)


def _serialize_agenda_order(order, detour_km=None):
    return {
        'id': order.id,
        'dailyNumber': order.daily_number,
        'requestedTime': order.requested_time,
        'customerName': order.customer_name,
        'totalPrice': order.total_price,
        'paymentMethod': PAYMENT_METHOD_LABELS.get(order.payment_method, order.payment_method),
        'paymentStatus': PAYMENT_STATUS_LABELS.get(order.payment_status, order.payment_status),
        'detourKm': detour_km,
    }


NO_OWNER_LOCATION_MESSAGE = ('Configura la ubicación de tu local en el Perfil del negocio para calcular '
                              'el desvío real del repartidor. Por ahora se muestra la distancia directa.')


@catalog.route('/agenda/cercania')
@login_required
@admin_required
@limiter.limit('1 per second')
def agenda_cercania():
    """Geocodes an address the owner types in and ranks today's confirmed despachos by
    how much each one would DETOUR the courier's trip if the new address were added to
    it - not by raw distance to the new address. Every courier starts from the local,
    so an order 500m from the local but on the way to a far-off existing order barely
    costs anything to bundle together, even though it sits "3 km" from that order in a
    straight line. Read-only, same as the rest of the Agenda - doesn't touch any order."""
    address = request.args.get('direccion', '').strip()
    if not address:
        return jsonify({'ok': False, 'message': 'Escribe una dirección para buscar.'}), 400

    coords = geocode(address)
    if coords is None:
        return jsonify({'ok': False, 'message': 'No pudimos encontrar esa dirección. Prueba con más detalle.'}), 400
    lat, lon = coords

    start_utc, end_utc = day_range_utc(datetime.now(BUSINESS_TZ).date())
    despachos = (Order.query
                 .filter(Order.created_at >= start_utc, Order.created_at < end_utc,
                         Order.status == 'Confirmed', Order.delivery_mode == 'envio',
                         Order.requested_for_tomorrow.isnot(True))
                 .all())

    # The detour math needs the local's own coordinates - the pin on the business
    # profile map, same field compute_shipping_cost() already reads for radius tiers.
    # It's optional there (nullable, never enforced at onboarding), so it can genuinely
    # be unset - falling back to plain point-to-point distance (today's behavior)
    # rather than 500ing, but the owner needs to know the ranking is less precise.
    owner = User.query.filter_by(is_owner=True).first()
    detour_available = bool(owner and owner.latitude is not None and owner.longitude is not None)
    dist_local_to_new = (_haversine_km(owner.latitude, owner.longitude, lat, lon)
                          if detour_available else None)

    # Orders without coordinates (old orders from before the address+pin requirement
    # was enforced - see A2.4/Paso1 diagnosis) can't be placed on the ranking, but
    # must never just vanish - they go in their own bucket, always returned.
    ranked = []
    without_location = []
    for order in despachos:
        if order.latitude is None or order.longitude is None:
            without_location.append(_serialize_agenda_order(order))
            continue

        dist_new_to_existing = _haversine_km(lat, lon, order.latitude, order.longitude)
        if detour_available:
            dist_local_to_existing = _haversine_km(owner.latitude, owner.longitude,
                                                     order.latitude, order.longitude)
            route_via_new_then_existing = dist_local_to_new + dist_new_to_existing
            route_via_existing_then_new = dist_local_to_existing + dist_new_to_existing
            detour_km = min(route_via_new_then_existing, route_via_existing_then_new) - dist_local_to_existing
        else:
            # No local coordinates to route from - the best we can do is the old
            # point-to-point distance, same ranking as before this feature existed.
            detour_km = dist_new_to_existing
        ranked.append((detour_km, order))

    ranked.sort(key=lambda pair: pair[0])
    results = [_serialize_agenda_order(order, detour_km) for detour_km, order in ranked]

    return jsonify({
        'ok': True,
        'results': results,
        'withoutLocation': without_location,
        'detourAvailable': detour_available,
        'message': None if detour_available else NO_OWNER_LOCATION_MESSAGE,
    })


@catalog.route('/orders')
@login_required
@admin_required
def orders():
    # created_at is stored in naive UTC - convert "today, in the business's own timezone"
    # into the matching UTC range so this can filter in SQL instead of loading every
    # historical order just to throw most of them away.
    start_utc, end_utc = day_range_utc(datetime.now(BUSINESS_TZ).date())

    todays_orders = (Order.query
                      .filter(Order.created_at >= start_utc, Order.created_at < end_utc)
                      .all())
    todays_orders.sort(key=_orders_sort_key)

    pending_count = sum(1 for order in todays_orders if order.status == 'Pending')
    confirmed_count = sum(1 for order in todays_orders if order.status == 'Confirmed')
    cancelled_count = sum(1 for order in todays_orders if order.status == 'Cancelled')
    couriers = Courier.query.order_by(Courier.name).all()
    courier_links = {order.id: _build_courier_links(order, couriers) for order in todays_orders}
    # joinedload for category/subcategory (to-one - one query, two extra JOINs) and
    # selectinload for option_groups/options (one-to-many - a couple of batched
    # queries total, not one per product/group the way a lazy access from inside a
    # Jinja loop would be). Serialized once into plain dicts and embedded as a single
    # JSON blob (see orders.html) instead of looping available_products inside every
    # order card's own <select> - with a real catalog (dozens of products) that used
    # to repeat the entire list once per order on the page.
    available_products = (Product.query.filter_by(is_active=True, sold_out=False)
                           .options(joinedload(Product.category), joinedload(Product.subcategory),
                                    selectinload(Product.option_groups).selectinload(ProductOptionGroup.options))
                           .order_by(Product.name).all())
    catalog_json = [
        {
            'id': product.id,
            'name': product.name,
            'price': product.price,
            'categoryId': product.category_id,
            'categoryName': product.category.name,
            'subcategoryId': product.subcategory_id,
            'subcategoryName': product.subcategory.name if product.subcategory else None,
            'optionGroups': [
                {
                    'id': group.id,
                    'name': group.name,
                    'required': group.required,
                    'multiSelect': group.multi_select,
                    'options': [{'id': option.id, 'name': option.name, 'priceDelta': option.price_delta}
                                for option in group.options],
                }
                for group in product.option_groups
            ],
        }
        for product in available_products
    ]
    owner = User.query.filter_by(is_owner=True).first()
    printer_configured = bool(owner and owner.printer_ip)
    # Subtotal isn't a stored column (only the final total_price is) - computed once
    # here, per order, so the template can show a real Subtotal/Envío/Descuento
    # breakdown instead of just the one collapsed Total it shows today.
    order_subtotals = {order.id: sum(item.price * item.quantity for item in order.order_items)
                        for order in todays_orders}
    return render_template('panel/orders.html', orders=todays_orders, pending_count=pending_count,
                            confirmed_count=confirmed_count, cancelled_count=cancelled_count,
                            courier_links=courier_links, couriers=couriers, catalog_json=catalog_json,
                            printer_configured=printer_configured, order_subtotals=order_subtotals,
                            cash_payment_summary=cash_payment_summary,
                            ORDER_STATUS_LABELS=ORDER_STATUS_LABELS, PAYMENT_METHOD_LABELS=PAYMENT_METHOD_LABELS)


@catalog.route('/orders/history')
@login_required
@admin_required
def order_history():
    all_orders = Order.query.order_by(Order.id.desc()).all()
    confirmed_count = sum(1 for order in all_orders if order.status == 'Confirmed')
    return render_template('panel/order_history.html', orders=all_orders, confirmed_count=confirmed_count,
                            ORDER_STATUS_LABELS=ORDER_STATUS_LABELS, PAYMENT_METHOD_LABELS=PAYMENT_METHOD_LABELS)


@catalog.route('/orders/export.csv')
@login_required
@admin_required
def export_orders_csv():
    """Universal, tool-agnostic export - the bridge to Excel, Loyverse, or whatever the
    owner already uses, instead of building a one-off integration with any single tool."""
    start = request.args.get('start')
    end = request.args.get('end')

    query = Order.query.order_by(Order.id)
    if start:
        start_utc, _end_utc = day_range_utc(datetime.strptime(start, '%Y-%m-%d').date())
        query = query.filter(Order.created_at >= start_utc)
    if end:
        _start_utc, end_utc = day_range_utc(datetime.strptime(end, '%Y-%m-%d').date())
        query = query.filter(Order.created_at < end_utc)

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        'ID', 'N° del día', 'Fecha', 'Hora pedido', 'Hora sugerida', 'Cliente', 'Teléfono', 'Tipo de entrega',
        'Dirección', 'Productos', 'Forma de pago', 'Monto con que paga', 'Subtotal', 'Envío',
        'Total', 'Estado', 'Estado de pago', 'Notas',
    ])
    for order in query.all():
        item_lines = []
        for item in order.order_items:
            product_name = item.product_name
            options = ', '.join(o.name for o in item.selected_options) if item.selected_options else ''
            label = f'{item.quantity}x {product_name}'
            if options:
                label += f' ({options})'
            if item.is_gift:
                label += ' (regalo)'
            item_lines.append(label)

        writer.writerow([
            order.id,
            order.daily_number if order.daily_number is not None else '',
            order.created_at_local.strftime('%Y-%m-%d'),
            order.created_at_local.strftime('%H:%M'),
            order.requested_time or '',
            order.customer_name,
            order.phone,
            'Despacho' if order.delivery_mode == 'envio' else 'Retiro',
            order.address or '',
            ' | '.join(item_lines),
            PAYMENT_METHOD_LABELS.get(order.payment_method, order.payment_method or ''),
            order.cash_amount or '',
            order.total_price - order.shipping_cost,
            order.shipping_cost,
            order.total_price,
            ORDER_STATUS_LABELS.get(order.status, order.status),
            PAYMENT_STATUS_LABELS.get(order.payment_status, order.payment_status),
            order.notes or '',
        ])

    filename = f'pedidos_{start or "todos"}_{end or "hoy"}.csv' if (start or end) else 'pedidos.csv'
    return Response(
        '﻿' + buffer.getvalue(),  # BOM so Excel opens the accented characters correctly
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


ORDER_ANCHOR_RE = re.compile(r'^order-\d+$')


def _redirect_back_to_orders():
    # An optional #order-<id> anchor (set by orders.html on every action form) lands
    # the owner back on the exact card they had open - without it, a full-page
    # redirect collapses every <details> and they lose their place. Validated against
    # a strict pattern since it becomes part of a Location header.
    next_url = request.form.get('next')
    if next_url not in (url_for('catalog.orders'), url_for('catalog.order_history'), url_for('catalog.agenda')):
        next_url = url_for('catalog.orders')
    anchor = request.form.get('anchor', '')
    if ORDER_ANCHOR_RE.match(anchor):
        next_url = f'{next_url}#{anchor}'
    return redirect(next_url)


CONFIRM_ORDER_MAX_ATTEMPTS = 5


@catalog.route('/orders/<int:order_id>/confirm', methods=['POST'])
@login_required
@admin_required
def confirm_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.status != 'Pending':
        flash(f'Este pedido ya está {ORDER_STATUS_LABELS[order.status].lower()} - no se puede confirmar.')
        return _redirect_back_to_orders()

    confirmed_at = datetime.utcnow()
    confirmed_date = confirmed_at.replace(tzinfo=ZoneInfo('UTC')).astimezone(BUSINESS_TZ).date()

    # daily_number = MAX(daily_number) of today + 1. The real guarantee against two
    # orders getting the same number is the DB's UNIQUE(confirmed_date, daily_number)
    # constraint, not this worker being single-threaded (-w 1 today, but that could
    # change). A collision is only possible with concurrent workers; on one, roll back
    # everything (the rollback discards ALL pending changes on `order`, so status,
    # confirmed_at, etc. must be re-applied too) and retry with a fresh MAX, capped so
    # a persistent problem surfaces as a visible error instead of retrying forever.
    for attempt in range(CONFIRM_ORDER_MAX_ATTEMPTS):
        order.status = 'Confirmed'
        order.confirmed_at = confirmed_at
        order.confirmed_date = confirmed_date
        # payment_status is NEVER auto-set here, regardless of payment_method - A2.2
        # assumed "transferencia = ya pagado al confirmar" because the ticket printed
        # "YA PAGADO" for it, but that's false in practice: some customers transfer
        # right away, others take a while. Every payment is confirmed manually by the
        # owner (WhatsApp receipt, cash from the courier, card charged) - see A2.2.1.
        last_number = (db.session.query(func.max(Order.daily_number))
                       .filter(Order.confirmed_date == confirmed_date).scalar())
        order.daily_number = (last_number or 0) + 1
        try:
            db.session.commit()
            break
        except IntegrityError:
            db.session.rollback()
    else:
        flash('No se pudo asignar el número de pedido del día - inténtalo de nuevo.')
        return _redirect_back_to_orders()

    flash('Pedido confirmado')
    return _redirect_back_to_orders()


@catalog.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.status not in ('Pending', 'Confirmed'):
        flash('Este pedido ya está cancelado.')
        return _redirect_back_to_orders()
    order.status = 'Cancelled'
    db.session.commit()
    flash('Pedido cancelado')
    return _redirect_back_to_orders()


@catalog.route('/orders/<int:order_id>/mark-paid', methods=['POST'])
@login_required
@admin_required
def mark_order_paid(order_id):
    order = Order.query.get_or_404(order_id)
    was_cancelled = order.status == 'Cancelled'
    order.payment_status = 'paid'
    db.session.commit()
    if was_cancelled:
        flash('Pedido marcado como pagado (nota: este pedido está cancelado)')
    else:
        flash('Pedido marcado como pagado')
    return _redirect_back_to_orders()


@catalog.route('/orders/<int:order_id>/mark-unpaid', methods=['POST'])
@login_required
@admin_required
def mark_order_unpaid(order_id):
    order = Order.query.get_or_404(order_id)
    order.payment_status = 'pending'
    db.session.commit()
    flash('Pedido marcado como pendiente de pago')
    return _redirect_back_to_orders()


@catalog.route('/orders/<int:order_id>/print', methods=['POST'])
@login_required
@admin_required
def print_order_ticket(order_id):
    order = Order.query.get_or_404(order_id)
    if order.status != 'Confirmed':
        flash('Solo se puede imprimir un pedido ya confirmado.')
        return _redirect_back_to_orders()

    owner = User.query.filter_by(is_owner=True).first()
    ok, error = _print_order_ticket(order, owner)
    flash('Ticket enviado a la impresora' if ok else error)
    return _redirect_back_to_orders()


@catalog.route('/orders/<int:order_id>/update-time', methods=['POST'])
@login_required
@admin_required
def update_order_time(order_id):
    order = Order.query.get_or_404(order_id)
    start = request.form.get('requested_time', '').strip()
    end = request.form.get('requested_time_end', '').strip()

    if not TIME_RE.match(start):
        flash('Ingresa una hora válida.')
        return _redirect_back_to_orders()
    if end and (not TIME_RE.match(end) or end <= start):
        flash('La hora "hasta" debe ser posterior a la hora de inicio.')
        return _redirect_back_to_orders()

    order.requested_time = start
    order.requested_time_end = end or None
    db.session.commit()
    flash('Horario del pedido actualizado')
    return _redirect_back_to_orders()


def _recalculate_order_total(order):
    """Re-evalúa cupón y bundle promo sobre el pedido ya editado (agregar/quitar
    productos por el panel puede cambiar qué aplica). unit_price siempre viene del
    snapshot en OrderItem.price, nunca del catálogo actual. Ítems huérfanos
    (product_id NULL) suman al subtotal pero se excluyen de promos y cupón, porque
    compute_bundle_discount/compute_coupon_discount asumen product no-None. Los
    regalos (is_gift) también se excluyen, igual que en create_order: un $0 en un
    "3x1" completaría un grupo y liberaría una unidad pagada."""
    items = OrderItem.query.filter_by(order_id=order.id).all()
    subtotal = sum(item.price * item.quantity for item in items)

    # The saved options go along (not []) so a tiered promo can take the variants back
    # out of the snapshot price - see _line_base_price.
    order_lines = [(item.product, item.quantity, item.selected_options, item.price)
                    for item in items if item.product is not None and not item.is_gift]

    bundle_discount = compute_bundle_discount(order_lines, _get_active_bundle_promos())

    coupon_discount = 0
    if order.coupon is not None:
        coupon_discount, _error = compute_coupon_discount(
            order.coupon, subtotal, order.shipping_cost, order_lines)

    order.discount_amount = coupon_discount
    order.bundle_discount_amount = bundle_discount
    order.total_price = max(subtotal + order.shipping_cost - bundle_discount - coupon_discount, 0)


@catalog.route('/orders/<int:order_id>/items/add', methods=['POST'])
@login_required
@admin_required
def add_order_item(order_id):
    order = Order.query.get_or_404(order_id)
    product = Product.query.get(request.form.get('product_id', type=int))
    quantity = request.form.get('quantity', type=int) or 1

    if not product or not product.is_active or product.sold_out or quantity < 1:
        flash('Selecciona un producto disponible y una cantidad válida.')
        return _redirect_back_to_orders()
    if product.stock_quantity is not None and product.stock_quantity < quantity:
        flash(f'Solo quedan {product.stock_quantity} unidades de {product.name}.')
        return _redirect_back_to_orders()

    # Same resolution create_order() uses for a checkout item - reused, not
    # reimplemented, so there's exactly one place that decides what a chosen option
    # actually costs. Raw strings (not type=int on getlist) on purpose: the function's
    # own int() conversion is what turns a bad id into an honest error message instead
    # of Werkzeug silently dropping it.
    option_ids = request.form.getlist('option_ids')
    selected_options, error = _resolve_selected_options(product, option_ids)
    if error:
        flash(error)
        return _redirect_back_to_orders()
    unit_price = product.price + sum(option.price_delta for option in selected_options)

    order_item = OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                            quantity=quantity, price=unit_price)
    db.session.add(order_item)
    db.session.flush()
    for option in selected_options:
        db.session.add(OrderItemOption(order_item_id=order_item.id, name=option.name, price_delta=option.price_delta))
    if product.stock_quantity is not None:
        product.stock_quantity = max(product.stock_quantity - quantity, 0)
        if product.stock_quantity == 0:
            product.sold_out = True
    db.session.flush()
    _recalculate_order_total(order)
    db.session.commit()
    flash(f'{product.name} agregado al pedido')
    return _redirect_back_to_orders()


@catalog.route('/orders/<int:order_id>/items/<int:item_id>/remove', methods=['POST'])
@login_required
@admin_required
def remove_order_item(order_id, item_id):
    order = Order.query.get_or_404(order_id)
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()

    if len(order.order_items) <= 1:
        flash('Un pedido debe tener al menos un producto - elimina el pedido completo si corresponde.')
        return _redirect_back_to_orders()

    product = item.product
    if product and product.stock_quantity is not None:
        product.stock_quantity += item.quantity
        if product.stock_quantity > 0:
            product.sold_out = False

    db.session.delete(item)
    db.session.flush()
    _recalculate_order_total(order)
    db.session.commit()
    flash('Producto quitado del pedido')
    return _redirect_back_to_orders()


@catalog.route('/orders/send-route', methods=['POST'])
@login_required
@admin_required
def send_route():
    order_ids = request.form.getlist('order_ids', type=int)
    marked = Order.query.filter(Order.id.in_(order_ids), Order.delivery_mode == 'envio').all()
    if not marked:
        flash('Marca al menos un pedido de despacho para armar el recorrido.')
        return redirect(url_for('catalog.orders'))

    orders = [order for order in marked if order.status == 'Confirmed']
    if not orders:
        flash('Ninguno de los pedidos marcados está confirmado; confírmalos antes de armar el recorrido.')
        return redirect(url_for('catalog.orders'))

    unconfirmed = [order for order in marked if order.status != 'Confirmed']
    if unconfirmed:
        names = ', '.join(order.customer_name for order in unconfirmed)
        flash(f'Recorrido enviado con {len(orders)} pedidos. '
              f'Quedaron afuera por no estar confirmados: {names}.')

    message = _build_route_message(orders)
    courier_id = request.form.get('courier_id', type=int)
    courier = Courier.query.get(courier_id) if courier_id else None
    base = f'https://wa.me/{courier.whatsapp_number}' if courier else 'https://wa.me/'
    return redirect(f'{base}?text={quote(message)}')


@catalog.route('/couriers')
@login_required
@owner_required
def couriers():
    all_couriers = Courier.query.order_by(Courier.name).all()
    return render_template('panel/couriers.html', couriers=all_couriers)


@catalog.route('/couriers/new', methods=['POST'])
@login_required
@owner_required
def create_courier():
    name = request.form.get('name', '').strip()
    whatsapp_number = re.sub(r'\D', '', request.form.get('whatsapp_number', ''))

    if not name or not whatsapp_number:
        flash('Completa nombre y número de WhatsApp del repartidor.')
    else:
        db.session.add(Courier(name=name, whatsapp_number=whatsapp_number))
        db.session.commit()
        flash('Repartidor agregado')
    return redirect(url_for('catalog.couriers'))


@catalog.route('/couriers/<int:courier_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_courier(courier_id):
    courier = Courier.query.get_or_404(courier_id)
    db.session.delete(courier)
    db.session.commit()
    flash('Repartidor eliminado')
    return redirect(url_for('catalog.couriers'))


# --- PWA: installable admin panel, no offline data (nothing to do offline anyway) ---

@catalog.route('/manifest.webmanifest')
def manifest():
    owner = User.query.filter_by(is_owner=True).first()
    business_name = owner.business_name if owner and owner.business_name else 'Menú Digital'
    theme_color = owner.primary_color if owner and owner.primary_color else '#4ecdc4'
    manifest_data = {
        'name': f'{business_name} - Panel',
        'short_name': 'Panel admin',
        'start_url': url_for('catalog.dashboard'),
        'scope': '/admin/',
        'display': 'standalone',
        'background_color': '#0d2236',
        'theme_color': theme_color,
        'icons': [
            {'src': url_for('catalog.pwa_icon', size=192), 'sizes': '192x192', 'type': 'image/png'},
            {'src': url_for('catalog.pwa_icon', size=512), 'sizes': '512x512', 'type': 'image/png'},
        ],
    }
    return Response(json.dumps(manifest_data), mimetype='application/manifest+json')


@catalog.route('/pwa-icon/<int:size>.png')
def pwa_icon(size):
    size = 512 if size >= 512 else 192
    owner = User.query.filter_by(is_owner=True).first()
    primary_color = owner.primary_color if owner and owner.primary_color else '#4ecdc4'

    icon = Image.new('RGB', (size, size), primary_color)
    logo_path = (os.path.join(current_app.config['LOGO_UPLOAD_DIR'], owner.logo_filename)
                 if owner and owner.logo_filename else None)

    if logo_path and os.path.exists(logo_path):
        logo = Image.open(logo_path).convert('RGBA')
        logo.thumbnail((int(size * 0.8), int(size * 0.8)), Image.LANCZOS)
        icon.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
    else:
        letter = business_initial(owner)
        draw = ImageDraw.Draw(icon)
        try:
            font = ImageFont.truetype('DejaVuSans-Bold.ttf', int(size * 0.5))
        except OSError:
            font = ImageFont.load_default()
        left, top, right, bottom = draw.textbbox((0, 0), letter, font=font)
        draw.text(((size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top), letter, fill='white', font=font)

    buf = BytesIO()
    icon.save(buf, format='PNG')
    return Response(buf.getvalue(), mimetype='image/png')


def business_initial(owner):
    if owner and owner.business_name:
        return owner.business_name.strip()[0].upper()
    return 'M'


@catalog.route('/sw.js')
def service_worker():
    content = (
        "self.addEventListener('install', () => self.skipWaiting());\n"
        "self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));\n"
        # Only pass through GET requests - re-issuing a POST via fetch(event.request)
        # can turn a redirect (e.g. our WhatsApp links) into a broken GET retry,
        # which then 405s on POST-only routes like "Enviar recorrido".
        "self.addEventListener('fetch', (event) => {\n"
        "  if (event.request.method !== 'GET') return;\n"
        "  event.respondWith(fetch(event.request));\n"
        "});\n"
    )
    return Response(content, mimetype='application/javascript')
