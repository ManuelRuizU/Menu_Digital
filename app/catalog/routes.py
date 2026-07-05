# app/catalog/routes.py
import json
import os
import re
from datetime import datetime, time, timedelta
from io import BytesIO
from urllib.parse import quote
from zoneinfo import ZoneInfo

from flask import current_app, flash, redirect, render_template, request, url_for, Response
from flask_login import login_required
from PIL import Image, ImageDraw, ImageFont
from escpos.printer import Network
from shapely.geometry import shape
from sqlalchemy import func

from app import db
from app.catalog import catalog
from app.decorators import admin_required, owner_required
from app.models import (BUSINESS_TZ, Category, Courier, DeliveryRadiusTier, DeliveryZone, Order, OrderItem,
                         Product, ProductOption, ProductOptionGroup, Subcategory, User)
from app.uploads import save_image

PAYMENT_METHOD_LABELS = {'efectivo': 'Efectivo', 'transferencia': 'Transferencia', 'tarjeta': 'Tarjeta al recibir'}


def _build_courier_message(order):
    """Everything a delivery driver needs for one order, as plain WhatsApp text."""
    if order.delivery_mode != 'envio':
        return None

    lines = [
        f'Pedido #{order.id}',
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
        if order.payment_method == 'efectivo' and order.cash_amount:
            change = order.cash_amount - order.total_price
            payment_line += f' - paga con ${order.cash_amount:.0f}, lleva ${max(change, 0):.0f} de vuelto'
        lines.append(payment_line)

    lines.append('')
    lines.append('Productos:')
    for item in order.order_items:
        product_name = item.product.name if item.product else 'Producto eliminado'
        options_text = ''
        if item.selected_options:
            options_text = ' (' + ', '.join(option.name for option in item.selected_options) + ')'
        lines.append(f'• {item.quantity}x {product_name}{options_text}')

    if order.notes:
        lines.append('')
        lines.append(f'Notas: {order.notes}')

    lines.append('')
    lines.append(f'Total: ${order.total_price:.0f}')

    return chr(10).join(lines)


def _build_courier_links(order, couriers):
    """One WhatsApp link per saved courier, or a single number-less link (modo libre)
    that lets the owner pick any contact, if no couriers are configured yet."""
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
        printer.text(f'ORDEN #{order.id}\n')
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
            product_name = item.product.name if item.product else 'Producto eliminado'
            printer.text(f'{item.quantity}x {product_name}\n')
            for option in item.selected_options:
                printer.text(f'   + {option.name}\n')
        if order.notes:
            printer.text(f'Nota: {order.notes}\n')
        printer.text('-' * width_chars + '\n')

        printer.set(align='center', bold=True)
        if order.payment_method == 'efectivo':
            printer.text('EFECTIVO\n')
            printer.set(align='center', bold=False)
            if order.cash_amount:
                change = max(order.cash_amount - order.total_price, 0)
                printer.text(f'Paga con: ${order.cash_amount:.0f}\n')
                printer.text(f'Vuelto: ${change:.0f}\n')
        elif order.payment_method == 'transferencia':
            printer.text('TRANSFERENCIA\n')
            printer.set(align='center', bold=False)
            printer.text('YA PAGADO\n')
        elif order.payment_method == 'tarjeta':
            printer.text('TARJETA\n')
            printer.set(align='center', bold=False)
            printer.text('Cobrar en la entrega\n(llevar máquina)\n')

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


@catalog.route('/categories/new', methods=['POST'])
@login_required
@admin_required
def create_category():
    name = request.form.get('name', '').strip()
    if not name:
        flash('El nombre de la categoría es obligatorio.')
        return redirect(url_for('catalog.categories'))

    db.session.add(Category(name=name))
    db.session.commit()
    flash('Categoría creada')
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

    db.session.add(Subcategory(name=name, category_id=category.id))
    db.session.commit()
    flash('Subcategoría creada')
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


def _product_form_context(product=None):
    return {
        'product': product,
        'categories': Category.query.order_by(Category.name).all(),
        'subcategories': Subcategory.query.order_by(Subcategory.name).all(),
    }


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
    price = request.form.get('price', type=float)
    category_id = request.form.get('category_id', type=int)
    subcategory_id = request.form.get('subcategory_id', type=int) or None

    category = Category.query.get(category_id) if category_id else None
    subcategory = Subcategory.query.get(subcategory_id) if subcategory_id else None
    if subcategory and subcategory.category_id != category_id:
        subcategory = None

    if not name or not description or price is None or category is None:
        flash('Completa nombre, descripción, precio y categoría del producto.')
        return render_template('panel/product_form.html', **_product_form_context(product if product.id else None))

    is_new = product.id is None
    product.name = name
    product.description = description
    product.price = price
    product.category_id = category.id
    product.subcategory_id = subcategory.id if subcategory else None
    product.stock_quantity = request.form.get('stock_quantity', type=int)
    if product.stock_quantity is not None:
        product.sold_out = product.stock_quantity <= 0
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
            return render_template('panel/product_form.html', **_product_form_context(product if not is_new else None))
        product.image_filename = new_filename

    db.session.commit()
    flash('Producto guardado')
    return redirect(url_for('catalog.products'))


@catalog.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    if product.orders:
        flash('Este producto tiene pedidos asociados; desactívalo en vez de eliminarlo.')
        return redirect(url_for('catalog.products'))

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


@catalog.route('/products/<int:product_id>/option-groups/new', methods=['POST'])
@login_required
@admin_required
def create_option_group(product_id):
    product = Product.query.get_or_404(product_id)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Ponle un nombre al grupo de variantes (ej. "Tamaño", "Extras").')
        return redirect(url_for('catalog.edit_product', product_id=product.id))

    db.session.add(ProductOptionGroup(
        product_id=product.id,
        name=name,
        required='required' in request.form,
        multi_select='multi_select' in request.form,
    ))
    db.session.commit()
    flash('Grupo de variantes agregado')
    return redirect(url_for('catalog.edit_product', product_id=product.id))


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
    price_delta = request.form.get('price_delta', type=float)
    if not name or price_delta is None:
        flash('Completa el nombre y el precio adicional de la opción (puede ser 0).')
        return redirect(url_for('catalog.edit_product', product_id=product_id))

    db.session.add(ProductOption(group_id=group.id, name=name, price_delta=price_delta))
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
    price = request.form.get('price', type=float)

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
    price = request.form.get('price', type=float)
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


@catalog.route('/dashboard')
@login_required
@admin_required
def dashboard():
    total_orders = Order.query.count()
    confirmed_orders = Order.query.filter_by(status='Confirmed').count()
    confirmation_rate = round(confirmed_orders / total_orders * 100) if total_orders else 0

    last_order_ids = db.session.query(func.max(Order.id)).group_by(Order.phone)
    customers = (
        Order.query.filter(Order.id.in_(last_order_ids))
        .order_by(Order.created_at.desc())
        .all()
    )
    order_counts = dict(db.session.query(Order.phone, func.count(Order.id)).group_by(Order.phone).all())
    owner = User.query.filter_by(is_owner=True).first()

    return render_template(
        'panel/dashboard.html',
        total_orders=total_orders,
        confirmed_orders=confirmed_orders,
        confirmation_rate=confirmation_rate,
        customers=customers,
        order_counts=order_counts,
        PAYMENT_METHOD_LABELS=PAYMENT_METHOD_LABELS,
        owner=owner,
    )


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


@catalog.route('/orders')
@login_required
@admin_required
def orders():
    # created_at is stored in naive UTC - convert "today, in the business's own timezone"
    # into the matching UTC range so this can filter in SQL instead of loading every
    # historical order just to throw most of them away.
    start_local = datetime.combine(datetime.now(BUSINESS_TZ).date(), time.min, tzinfo=BUSINESS_TZ)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
    end_utc = end_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)

    todays_orders = (Order.query
                      .filter(Order.created_at >= start_utc, Order.created_at < end_utc)
                      .all())
    todays_orders.sort(key=lambda order: order.requested_time or '99:99')

    confirmed_count = sum(1 for order in todays_orders if order.status == 'Confirmed')
    couriers = Courier.query.order_by(Courier.name).all()
    courier_links = {order.id: _build_courier_links(order, couriers) for order in todays_orders}
    available_products = (Product.query.filter_by(is_active=True, sold_out=False)
                           .order_by(Product.name).all())
    owner = User.query.filter_by(is_owner=True).first()
    printer_configured = bool(owner and owner.printer_ip)
    return render_template('panel/orders.html', orders=todays_orders, confirmed_count=confirmed_count,
                            courier_links=courier_links, couriers=couriers, available_products=available_products,
                            printer_configured=printer_configured)


@catalog.route('/orders/history')
@login_required
@admin_required
def order_history():
    all_orders = Order.query.order_by(Order.id.desc()).all()
    confirmed_count = sum(1 for order in all_orders if order.status == 'Confirmed')
    return render_template('panel/order_history.html', orders=all_orders, confirmed_count=confirmed_count)


def _redirect_back_to_orders():
    next_url = request.form.get('next')
    if next_url in (url_for('catalog.orders'), url_for('catalog.order_history')):
        return redirect(next_url)
    return redirect(url_for('catalog.orders'))


@catalog.route('/orders/<int:order_id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    order.status = 'Pending' if order.status == 'Confirmed' else 'Confirmed'
    db.session.commit()
    flash('Pedido confirmado' if order.status == 'Confirmed' else 'Pedido marcado como pendiente')
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


TIME_RE = re.compile(r'^\d{2}:\d{2}$')


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
    items = OrderItem.query.filter_by(order_id=order.id).all()
    subtotal = sum(item.price * item.quantity for item in items)
    order.total_price = subtotal + order.shipping_cost


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

    db.session.add(OrderItem(order_id=order.id, product_id=product.id, quantity=quantity, price=product.price))
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
    orders = Order.query.filter(Order.id.in_(order_ids), Order.delivery_mode == 'envio').all()
    if not orders:
        flash('Marca al menos un pedido de despacho para armar el recorrido.')
        return redirect(url_for('catalog.orders'))

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
