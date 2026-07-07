import json
import math
import re
from datetime import datetime

from flask import current_app, jsonify, render_template, request, url_for
from shapely.geometry import Point, shape

from app.main import main
from app.models import (BUSINESS_TZ, BundlePromo, BusinessHours, Coupon, CouponRedemption, DAY_NAMES,
                         DeliveryRadiusTier, DeliveryZone, Order, OrderItem, OrderItemOption, Product,
                         ProductOption, THEMES, User)
from app import csrf, db, limiter


def get_owner():
    return User.query.filter_by(is_owner=True).first()


def has_delivery_configured():
    return db.session.query(DeliveryRadiusTier.query.exists()).scalar() or \
        db.session.query(DeliveryZone.query.exists()).scalar()


def resolve_hours_for_day(day_index):
    """The BusinessHours row for the given weekday (0=Monday...6=Sunday), or None if no
    day has ever been configured at all - a fresh install has no schedule, so nothing
    should be restricted. Split out from get_hours_for_today() so tests can pass an
    explicit day instead of depending on whatever day they happen to run on."""
    any_configured = db.session.query(BusinessHours.query.filter(BusinessHours.opens_at.isnot(None)).exists()).scalar()
    if not any_configured:
        return None
    return BusinessHours.query.filter_by(day_of_week=day_index).first()


def get_hours_for_today():
    return resolve_hours_for_day(datetime.now(BUSINESS_TZ).weekday())


def is_within_business_hours(time_str, opens_at, closes_at):
    """True when no hours are configured, or time_str falls inside [opens_at, closes_at].

    Handles ranges that cross midnight (e.g. opens_at='18:00', closes_at='02:00').
    """
    if not opens_at or not closes_at:
        return True
    if opens_at <= closes_at:
        return opens_at <= time_str <= closes_at
    return time_str >= opens_at or time_str <= closes_at


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def compute_shipping_cost(lat, lng):
    """Return (cost, covered). Polygon zones take precedence over radius tiers."""
    point = Point(lng, lat)
    for zone in DeliveryZone.query.order_by(DeliveryZone.id).all():
        try:
            polygon = shape(json.loads(zone.geojson))
        except (ValueError, TypeError):
            continue
        if polygon.contains(point):
            return zone.price, True

    owner = get_owner()
    if not owner or owner.latitude is None or owner.longitude is None:
        return None, False

    distance_km = _haversine_km(owner.latitude, owner.longitude, lat, lng)
    tier = (DeliveryRadiusTier.query
            .filter(DeliveryRadiusTier.min_km <= distance_km, DeliveryRadiusTier.max_km > distance_km)
            .order_by(DeliveryRadiusTier.min_km)
            .first())
    if tier is None:
        return None, False
    return tier.price, True


def _gift_is_available(owner):
    if not owner or not owner.gift_threshold_amount or not owner.gift_product_id:
        return False
    product = owner.gift_product
    if not product or not product.is_active or product.sold_out:
        return False
    if product.stock_quantity is not None and product.stock_quantity < 1:
        return False
    return True


@main.route('/')
def index():
    owner = get_owner()
    gift_available = _gift_is_available(owner)
    logo_url = url_for('static', filename='uploads/logos/' + owner.logo_filename) if owner and owner.logo_filename else None
    theme = owner.theme if owner and owner.theme in THEMES else 'oscuro'
    theme_defaults = THEMES[theme]

    hours_today = get_hours_for_today()
    closed_by_schedule = hours_today is not None and hours_today.is_closed
    is_closed_temporarily = owner.is_closed_temporarily if owner else False

    if is_closed_temporarily:
        closed_message = owner.closed_message
    elif closed_by_schedule:
        closed_message = f'Hoy {DAY_NAMES[hours_today.day_of_week]} no atendemos. ¡Vuelve otro día!'
    else:
        closed_message = None

    return render_template(
        'index.html',
        is_closed=(is_closed_temporarily or closed_by_schedule),
        closed_message=closed_message,
        theme=theme,
        business_name=(owner.business_name if owner and owner.business_name else 'Menú digital'),
        slogan=(owner.slogan if owner else None),
        business_address=(owner.address if owner else None),
        maps_url=(f'https://www.google.com/maps/search/?api=1&query={owner.latitude},{owner.longitude}'
                   if owner and owner.latitude is not None and owner.longitude is not None else None),
        logo_url=logo_url,
        primary_color=(owner.primary_color if owner and owner.primary_color else theme_defaults['primary']),
        accent_color=(owner.accent_color if owner and owner.accent_color else theme_defaults['accent']),
        accepts_cash=(owner.accepts_cash if owner else True),
        accepts_transfer=(owner.accepts_transfer if owner else True),
        accepts_card=(owner.accepts_card if owner else True),
        bank_details=(owner.bank_details if owner else None),
        has_delivery=has_delivery_configured(),
        business_lat=(owner.latitude if owner and owner.latitude is not None else -33.4489),
        business_lng=(owner.longitude if owner and owner.longitude is not None else -70.6693),
        min_delivery_order=(owner.min_delivery_order if owner else None),
        gift_threshold_amount=(owner.gift_threshold_amount if gift_available else None),
        gift_product_name=(owner.gift_product.name if gift_available else None),
        opens_at=(hours_today.opens_at if hours_today else None),
        closes_at=(hours_today.closes_at if hours_today else None),
        creator_name=current_app.config.get('CREATOR_NAME'),
        creator_whatsapp=current_app.config.get('CREATOR_WHATSAPP'),
    )


@main.route('/privacidad')
def privacy():
    owner = get_owner()
    theme = owner.theme if owner and owner.theme in THEMES else 'oscuro'
    theme_defaults = THEMES[theme]
    return render_template(
        'privacy.html',
        theme=theme,
        business_name=(owner.business_name if owner and owner.business_name else 'Menú digital'),
        primary_color=(owner.primary_color if owner and owner.primary_color else theme_defaults['primary']),
        accent_color=(owner.accent_color if owner and owner.accent_color else theme_defaults['accent']),
        whatsapp_number=(owner.whatsapp_number if owner else None),
    )


@main.route('/api/products')
def products_api():
    products = (Product.query.filter_by(is_active=True)
                .order_by(Product.category_id, Product.subcategory_id, Product.name)
                .all())
    payload = [
        {
            'id': product.id,
            'name': product.name,
            'description': product.description,
            'price': product.price,
            'originalPrice': product.original_price,
            'categoryId': product.category_id,
            'category': product.category.name,
            'subcategoryId': product.subcategory_id,
            'subcategory': product.subcategory.name if product.subcategory else None,
            'soldOut': product.sold_out,
            'featured': product.is_featured,
            'imageUrl': (url_for('static', filename='uploads/products/' + product.image_filename)
                         if product.image_filename else None),
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
        for product in products
    ]
    return jsonify(payload)


@main.route('/api/whatsapp-number')
def whatsapp_number_api():
    owner = get_owner()
    number = owner.whatsapp_number if owner and owner.whatsapp_number else ''
    return jsonify({'whatsappNumber': number})


@main.route('/api/banner-coupons')
def banner_coupons_api():
    """Coupons the owner opted to show in the public menu's banner carousel - only the
    checks that don't need a customer yet (active, dated, total uses left); the per-customer
    limit and a final re-check still happen when the code is actually applied/redeemed."""
    today = datetime.now(BUSINESS_TZ).date()
    candidates = Coupon.query.filter_by(show_in_banner=True, is_active=True).all()
    payload = []
    for coupon in candidates:
        if coupon.valid_from and today < coupon.valid_from:
            continue
        if coupon.valid_until and today > coupon.valid_until:
            continue
        if coupon.max_total_uses is not None and coupon.total_uses >= coupon.max_total_uses:
            continue
        payload.append({
            'code': coupon.code,
            'discountPercent': coupon.discount_percent,
            'scope': coupon.scope,
            'validUntil': coupon.valid_until.isoformat() if coupon.valid_until else None,
            'bannerImageUrl': (url_for('static', filename='uploads/coupons/' + coupon.banner_image_filename)
                                if coupon.banner_image_filename else None),
        })
    return jsonify(payload)


@main.route('/api/bundle-promos')
def bundle_promos_api():
    payload = [
        {
            'id': promo.id,
            'label': promo.label,
            'buyQuantity': promo.buy_quantity,
            'payQuantity': promo.pay_quantity,
            'productIds': [product.id for product in promo.products],
        }
        for promo in _get_active_bundle_promos()
    ]
    return jsonify(payload)


@main.route('/api/shipping-cost', methods=['POST'])
@csrf.exempt
def shipping_cost_api():
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data.get('lat'))
        lng = float(data.get('lng'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'message': 'Coordenadas inválidas.'}), 400

    cost, covered = compute_shipping_cost(lat, lng)
    return jsonify({'covered': covered, 'shippingCost': cost if covered else None})


def _resolve_selected_options(product, selected_option_ids):
    """Validate the option ids a customer picked for one product against that
    product's own option groups (required / single-vs-multi-select).

    Returns (selected_options, error_message) - never trust the ids the client sent.
    """
    if not isinstance(selected_option_ids, list):
        return [], 'Selección de variantes inválida.'
    try:
        selected_option_ids = {int(option_id) for option_id in selected_option_ids}
    except (TypeError, ValueError):
        return [], 'Selección de variantes inválida.'

    valid_option_ids = {option.id for group in product.option_groups for option in group.options}
    if not selected_option_ids.issubset(valid_option_ids):
        return [], 'Una de las variantes elegidas ya no existe.'

    selected_options = ProductOption.query.filter(ProductOption.id.in_(selected_option_ids)).all() if selected_option_ids else []
    selected_by_group = {}
    for option in selected_options:
        selected_by_group.setdefault(option.group_id, []).append(option)

    for group in product.option_groups:
        chosen = selected_by_group.get(group.id, [])
        if group.required and not chosen:
            return [], f'Elige una opción para "{group.name}".'
        if not group.multi_select and len(chosen) > 1:
            return [], f'Solo puedes elegir una opción para "{group.name}".'

    return selected_options, None


def _resolve_cart_items(items):
    """Validate and price each cart line against the current catalog - never trust the
    client's prices. Returns (order_lines, subtotal, error_message); order_lines is a list
    of (product, quantity, selected_options, unit_price)."""
    order_lines = []
    subtotal = 0
    for item in items:
        product_id = item.get('id')
        quantity = item.get('quantity')
        if not isinstance(quantity, int) or quantity < 1:
            return None, None, 'Cantidad inválida en el pedido.'
        product = Product.query.get(product_id)
        if product is None or not product.is_active or product.sold_out:
            return None, None, 'Uno de los productos ya no está disponible.'
        if product.stock_quantity is not None and product.stock_quantity < quantity:
            return None, None, f'Solo quedan {product.stock_quantity} unidades de {product.name}.'

        selected_options, error = _resolve_selected_options(product, item.get('options', []))
        if error:
            return None, None, error
        unit_price = product.price + sum(option.price_delta for option in selected_options)

        order_lines.append((product, quantity, selected_options, unit_price))
        subtotal += unit_price * quantity

    return order_lines, subtotal, None


def _get_active_bundle_promos():
    today = datetime.now(BUSINESS_TZ).date()
    promos = BundlePromo.query.filter_by(is_active=True).all()
    return [p for p in promos
            if (not p.valid_from or today >= p.valid_from) and (not p.valid_until or today <= p.valid_until)]


def compute_bundle_discount(order_lines, promos):
    """Automatic "2x1"/"3x2" promos - no code needed. For each promo, flatten the matching
    products' units, sort by price descending, and group them into chunks of buy_quantity;
    within each *complete* chunk the cheapest (buy_quantity - pay_quantity) units are free.
    A leftover partial chunk (not enough units yet) gets no discount."""
    total_discount = 0
    for promo in promos:
        product_ids = {product.id for product in promo.products}
        unit_prices = []
        for product, quantity, _options, unit_price in order_lines:
            if product.id in product_ids:
                unit_prices.extend([unit_price] * quantity)
        if len(unit_prices) < promo.buy_quantity:
            continue

        unit_prices.sort(reverse=True)
        free_quantity = promo.buy_quantity - promo.pay_quantity
        num_full_groups = len(unit_prices) // promo.buy_quantity
        for group_index in range(num_full_groups):
            start = group_index * promo.buy_quantity
            group = unit_prices[start:start + promo.buy_quantity]
            if free_quantity > 0:
                total_discount += sum(group[-free_quantity:])

    return round(total_discount)


def normalize_phone(phone):
    return re.sub(r'\D', '', phone or '')


def _resolve_coupon(code):
    code = (code or '').strip()
    if not code:
        return None
    return Coupon.query.filter(db.func.upper(Coupon.code) == code.upper()).first()


def validate_coupon(coupon, phone, subtotal, shipping_cost, order_lines):
    """Returns (discount_amount, error_message) - error_message is None on success.
    Re-checks every limit against the database (redemption rows), never a client-sent number."""
    if coupon is None or not coupon.is_active:
        return 0, 'Ese cupón no existe o ya no está activo.'

    today = datetime.now(BUSINESS_TZ).date()
    if coupon.valid_from and today < coupon.valid_from:
        return 0, 'Este cupón todavía no está vigente.'
    if coupon.valid_until and today > coupon.valid_until:
        return 0, 'Este cupón ya venció.'

    if coupon.max_total_uses is not None:
        total_used = CouponRedemption.query.filter_by(coupon_id=coupon.id).count()
        if total_used >= coupon.max_total_uses:
            return 0, 'Este cupón ya alcanzó su límite de usos.'

    phone_digits = normalize_phone(phone)
    if coupon.max_uses_per_customer is not None:
        if not phone_digits:
            return 0, 'Ingresa tu teléfono antes de aplicar el cupón.'
        customer_used = CouponRedemption.query.filter_by(coupon_id=coupon.id, phone_digits=phone_digits).count()
        if customer_used >= coupon.max_uses_per_customer:
            return 0, 'Ya usaste este cupón antes.'

    if coupon.scope == 'products':
        coupon_product_ids = {product.id for product in coupon.products}
        applicable = sum(unit_price * quantity for product, quantity, _options, unit_price in order_lines
                          if product.id in coupon_product_ids)
        if applicable <= 0:
            return 0, 'Este cupón no aplica a los productos de tu carrito.'
    else:
        applicable = subtotal + shipping_cost

    return round(applicable * coupon.discount_percent / 100), None


@main.route('/api/apply-coupon', methods=['POST'])
@csrf.exempt
@limiter.limit('30 per minute')
def apply_coupon_api():
    data = request.get_json(silent=True) or {}
    items = data.get('items', [])
    phone = data.get('phone')
    delivery_mode = data.get('deliveryMode') or 'retira'

    order_lines, subtotal, error = _resolve_cart_items(items)
    if error:
        return jsonify({'ok': False, 'message': error}), 400

    shipping_cost = 0
    if delivery_mode == 'envio':
        try:
            lat = float(data.get('lat'))
            lng = float(data.get('lng'))
        except (TypeError, ValueError):
            lat = lng = None
        if lat is not None and lng is not None:
            cost, covered = compute_shipping_cost(lat, lng)
            shipping_cost = cost if covered else 0

    bundle_discount = compute_bundle_discount(order_lines, _get_active_bundle_promos())

    coupon = _resolve_coupon(data.get('code'))
    discount_amount, error = validate_coupon(coupon, phone, subtotal - bundle_discount, shipping_cost, order_lines)
    if error:
        return jsonify({'ok': False, 'message': error}), 400

    return jsonify({
        'ok': True,
        'code': coupon.code,
        'discountPercent': coupon.discount_percent,
        'scope': coupon.scope,
        'discountAmount': discount_amount,
    })


@main.route('/api/orders', methods=['POST'])
@csrf.exempt
@limiter.limit('20 per minute')
def create_order():
    data = request.get_json(silent=True) or {}
    items = data.get('items', [])
    customer_name = data.get('customerName')
    phone = data.get('phone')
    address = data.get('address')
    delivery_mode = data.get('deliveryMode') or 'retira'
    payment_method = data.get('paymentMethod')
    notes = (data.get('notes') or '').strip()[:500] or None
    requested_time = data.get('requestedTime')
    if not requested_time or not re.match(r'^\d{2}:\d{2}$', requested_time):
        requested_time = None

    if not items or not customer_name or not phone:
        return jsonify({'ok': False, 'message': 'Faltan datos del pedido.'}), 400

    owner = get_owner()
    if owner and owner.is_closed_temporarily:
        return jsonify({'ok': False, 'message': 'Este negocio está cerrado temporalmente y no puede recibir pedidos.'}), 400

    hours_today = get_hours_for_today()
    if hours_today is not None and hours_today.is_closed:
        return jsonify({'ok': False, 'message': f'Hoy {hours_today.day_name} no atendemos.'}), 400

    enabled_methods = {
        'efectivo': owner.accepts_cash if owner else True,
        'transferencia': owner.accepts_transfer if owner else True,
        'tarjeta': owner.accepts_card if owner else True,
    }
    if payment_method not in enabled_methods or not enabled_methods[payment_method]:
        return jsonify({'ok': False, 'message': 'Ese método de pago no está disponible.'}), 400

    if hours_today is not None and requested_time and not is_within_business_hours(requested_time, hours_today.opens_at, hours_today.closes_at):
        return jsonify({
            'ok': False,
            'message': f'Hoy solo recibimos pedidos entre las {hours_today.opens_at} y las {hours_today.closes_at}.',
        }), 400

    cash_amount = None
    if payment_method == 'efectivo':
        try:
            cash_amount = float(data.get('cashAmount'))
        except (TypeError, ValueError):
            cash_amount = None

    shipping_cost = 0
    lat = lng = None
    if delivery_mode == 'envio':
        if not has_delivery_configured():
            return jsonify({'ok': False, 'message': 'Este negocio no ofrece despacho.'}), 400
        try:
            lat = float(data.get('lat'))
            lng = float(data.get('lng'))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'message': 'Selecciona una ubicación de despacho válida.'}), 400

        shipping_cost, covered = compute_shipping_cost(lat, lng)
        if not covered:
            return jsonify({'ok': False, 'message': 'Esa dirección está fuera de la zona de reparto.'}), 400

    order_lines, subtotal, error = _resolve_cart_items(items)
    if error:
        return jsonify({'ok': False, 'message': error}), 400

    if delivery_mode == 'envio' and owner and owner.min_delivery_order and subtotal < owner.min_delivery_order:
        return jsonify({
            'ok': False,
            'message': f'El pedido mínimo para despacho es ${owner.min_delivery_order:.0f}.',
        }), 400

    bundle_discount = compute_bundle_discount(order_lines, _get_active_bundle_promos())

    coupon = None
    discount_amount = 0
    coupon_code = data.get('couponCode')
    if coupon_code:
        coupon = _resolve_coupon(coupon_code)
        discount_amount, error = validate_coupon(coupon, phone, subtotal - bundle_discount, shipping_cost, order_lines)
        if error:
            return jsonify({'ok': False, 'message': error}), 400

    try:
        order = Order(
            customer_name=customer_name,
            phone=phone,
            address=address,
            delivery_mode=delivery_mode,
            payment_method=payment_method,
            cash_amount=cash_amount,
            notes=notes,
            requested_time=requested_time,
            latitude=lat,
            longitude=lng,
            shipping_cost=shipping_cost,
            total_price=subtotal + shipping_cost - bundle_discount - discount_amount,
            coupon_id=coupon.id if coupon else None,
            discount_amount=discount_amount,
            bundle_discount_amount=bundle_discount,
            status='Pending',
        )
        db.session.add(order)
        db.session.flush()
        for product, quantity, selected_options, unit_price in order_lines:
            order_item = OrderItem(order_id=order.id, product_id=product.id, quantity=quantity, price=unit_price)
            db.session.add(order_item)
            db.session.flush()
            for option in selected_options:
                db.session.add(OrderItemOption(order_item_id=order_item.id, name=option.name, price_delta=option.price_delta))
            if product.stock_quantity is not None:
                product.stock_quantity = max(product.stock_quantity - quantity, 0)
                if product.stock_quantity == 0:
                    product.sold_out = True

        effective_total = subtotal + shipping_cost - bundle_discount - discount_amount
        if _gift_is_available(owner) and effective_total >= owner.gift_threshold_amount:
            gift_product = owner.gift_product
            gift_item = OrderItem(order_id=order.id, product_id=gift_product.id, quantity=1, price=0)
            db.session.add(gift_item)
            if gift_product.stock_quantity is not None:
                gift_product.stock_quantity = max(gift_product.stock_quantity - 1, 0)
                if gift_product.stock_quantity == 0:
                    gift_product.sold_out = True

        if coupon:
            db.session.add(CouponRedemption(coupon_id=coupon.id, order_id=order.id, phone_digits=normalize_phone(phone)))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to save order for %s (%s)', customer_name, phone)
        return jsonify({'ok': False, 'message': 'No se pudo guardar el pedido.'}), 500

    return jsonify({'ok': True, 'message': 'Pedido guardado y listo para enviar por WhatsApp.', 'orderId': order.id,
                     'discountAmount': discount_amount})
