import json
from datetime import date, timedelta

from app.models import (BundlePromo, Category, Coupon, CouponRedemption, DeliveryZone, Order, OrderItem, Product,
                        User)
from app.main import routes as main_routes


def _create_product(db, price=1000, name='Producto'):
    category = Category.query.first()
    if category is None:
        category = Category(name='Categoria')
        db.session.add(category)
        db.session.commit()
    product = Product(name=name, description='Test', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


def _create_coupon(db, **overrides):
    defaults = dict(code='PRIMERACOMPRA', discount_percent=10, scope='order', is_active=True)
    defaults.update(overrides)
    coupon = Coupon(**defaults)
    db.session.add(coupon)
    db.session.commit()
    return coupon


def _create_delivery_zone(db, price=1500):
    geojson = json.dumps({
        'type': 'Polygon',
        'coordinates': [[[-71, -34], [-69, -34], [-69, -33], [-71, -33], [-71, -34]]],
    })
    zone = DeliveryZone(name='Zona test', price=price, geojson=geojson)
    db.session.add(zone)
    db.session.commit()
    return zone


PHONE = '56911112222'


def _create_dummy_order(db, phone='56900000000'):
    order = Order(customer_name='Otro cliente', phone=phone, delivery_mode='retira',
                   payment_method='efectivo', total_price=1000, status='Pending')
    db.session.add(order)
    db.session.commit()
    return order


# --- /api/apply-coupon (cart preview) ---

def test_apply_coupon_order_scope_discounts_subtotal(client, db):
    product = _create_product(db, price=1000)
    _create_coupon(db, discount_percent=10, scope='order')

    resp = client.post('/api/apply-coupon', json={
        'code': 'primeracompra', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': 2}],
    })
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['ok'] is True
    assert data['discountAmount'] == 200  # 10% of 2000


def test_apply_coupon_order_scope_does_not_discount_shipping_by_default(client, db):
    product = _create_product(db, price=1000)
    _create_coupon(db, discount_percent=10, scope='order')  # applies_to_shipping defaults to False
    _create_delivery_zone(db, price=1500)

    resp = client.post('/api/apply-coupon', json={
        'code': 'primeracompra', 'phone': PHONE, 'deliveryMode': 'envio',
        'items': [{'id': product.id, 'quantity': 2}],
        'lat': -33.5, 'lng': -70.5,
    })
    data = resp.get_json()
    assert data['ok'] is True
    assert data['discountAmount'] == 200  # 10% of the 2000 subtotal only, shipping (1500) excluded


def test_apply_coupon_order_scope_discounts_shipping_when_flag_set(client, db):
    product = _create_product(db, price=1000)
    _create_coupon(db, discount_percent=10, scope='order', applies_to_shipping=True)
    _create_delivery_zone(db, price=1500)

    resp = client.post('/api/apply-coupon', json={
        'code': 'primeracompra', 'phone': PHONE, 'deliveryMode': 'envio',
        'items': [{'id': product.id, 'quantity': 2}],
        'lat': -33.5, 'lng': -70.5,
    })
    data = resp.get_json()
    assert data['ok'] is True
    assert data['discountAmount'] == 350  # 10% of subtotal (2000) + shipping (1500)


def test_apply_coupon_products_scope_only_discounts_matching_product(client, db):
    matching = _create_product(db, price=1000, name='Roll Ebi Tempura')
    other = _create_product(db, price=2000, name='Té helado')
    coupon = _create_coupon(db, code='ROLLDESCUENTO', discount_percent=50, scope='products')
    coupon.products = [matching]
    db.session.commit()

    resp = client.post('/api/apply-coupon', json={
        'code': 'ROLLDESCUENTO', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': matching.id, 'quantity': 1}, {'id': other.id, 'quantity': 1}],
    })
    data = resp.get_json()
    assert data['ok'] is True
    assert data['discountAmount'] == 500  # 50% of matching product's 1000 only, not the 2000 one


def test_apply_coupon_rejects_unknown_code(client, db):
    product = _create_product(db)
    resp = client.post('/api/apply-coupon', json={
        'code': 'NOEXISTE', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': 1}],
    })
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False


def test_apply_coupon_rejects_inactive(client, db):
    product = _create_product(db)
    _create_coupon(db, is_active=False)
    resp = client.post('/api/apply-coupon', json={
        'code': 'PRIMERACOMPRA', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': 1}],
    })
    assert resp.get_json()['ok'] is False


def test_apply_coupon_rejects_before_valid_from(client, db):
    product = _create_product(db)
    _create_coupon(db, valid_from=date.today() + timedelta(days=1))
    resp = client.post('/api/apply-coupon', json={
        'code': 'PRIMERACOMPRA', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': 1}],
    })
    assert resp.get_json()['ok'] is False


def test_apply_coupon_rejects_after_valid_until(client, db):
    product = _create_product(db)
    _create_coupon(db, valid_until=date.today() - timedelta(days=1))
    resp = client.post('/api/apply-coupon', json={
        'code': 'PRIMERACOMPRA', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': 1}],
    })
    assert resp.get_json()['ok'] is False


def test_apply_coupon_accepts_on_the_valid_day(client, db):
    product = _create_product(db, price=1000)
    _create_coupon(db, code='DIADELSUSHI10', discount_percent=10,
                    valid_from=date.today(), valid_until=date.today())
    resp = client.post('/api/apply-coupon', json={
        'code': 'DIADELSUSHI10', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': 1}],
    })
    data = resp.get_json()
    assert data['ok'] is True
    assert data['discountAmount'] == 100


def test_apply_coupon_rejects_when_total_uses_exhausted(client, db):
    product = _create_product(db)
    coupon = _create_coupon(db, max_total_uses=1)
    used_order = _create_dummy_order(db)
    db.session.add(CouponRedemption(coupon_id=coupon.id, order_id=used_order.id, phone_digits='56900000000'))
    db.session.commit()

    resp = client.post('/api/apply-coupon', json={
        'code': 'PRIMERACOMPRA', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': 1}],
    })
    assert resp.get_json()['ok'] is False


def test_apply_coupon_rejects_when_customer_already_used_it(client, db):
    product = _create_product(db)
    coupon = _create_coupon(db, max_uses_per_customer=1)
    used_order = _create_dummy_order(db, phone=PHONE)
    db.session.add(CouponRedemption(coupon_id=coupon.id, order_id=used_order.id, phone_digits=PHONE))
    db.session.commit()

    resp = client.post('/api/apply-coupon', json={
        'code': 'PRIMERACOMPRA', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': 1}],
    })
    assert resp.get_json()['ok'] is False


def test_apply_coupon_allows_a_different_customer_when_per_customer_limit_reached(client, db):
    product = _create_product(db, price=1000)
    coupon = _create_coupon(db, max_uses_per_customer=1)
    used_order = _create_dummy_order(db)
    db.session.add(CouponRedemption(coupon_id=coupon.id, order_id=used_order.id, phone_digits='56900000000'))
    db.session.commit()

    resp = client.post('/api/apply-coupon', json={
        'code': 'PRIMERACOMPRA', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': 1}],
    })
    assert resp.get_json()['ok'] is True


# --- /api/orders (actual redemption on checkout) ---

def test_create_order_applies_coupon_and_records_redemption(client, db, order_payload):
    product = _create_product(db, price=1000)
    coupon = _create_coupon(db, discount_percent=10)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='primeracompra'))
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['ok'] is True
    assert data['discountAmount'] == 100

    redemptions = CouponRedemption.query.filter_by(coupon_id=coupon.id).all()
    assert len(redemptions) == 1
    assert redemptions[0].phone_digits == PHONE


def test_create_order_rejects_invalid_coupon_without_creating_order(client, db, order_payload):
    product = _create_product(db, price=1000, name='Rechazo')

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='NOEXISTE'))
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False
    assert Order.query.count() == 0


def test_create_order_enforces_per_customer_limit_across_two_orders(client, db, order_payload):
    product = _create_product(db, price=1000, name='Limitado')
    _create_coupon(db, code='UNAVEZ', discount_percent=10, max_uses_per_customer=1)

    first = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='UNAVEZ'))
    assert first.get_json()['ok'] is True

    second = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='UNAVEZ'))
    assert second.status_code == 400
    assert second.get_json()['ok'] is False


# --- Minimum purchase (min_order_amount): compared against products minus 2x1, never shipping ---

def _apply(client, product, quantity, delivery_mode='retira', **extra):
    return client.post('/api/apply-coupon', json={
        'code': 'primeracompra', 'phone': PHONE, 'deliveryMode': delivery_mode,
        'items': [{'id': product.id, 'quantity': quantity}], **extra,
    })


def test_apply_coupon_rejects_below_min_order_amount(client, db):
    product = _create_product(db, price=1000)
    _create_coupon(db, discount_percent=10, min_order_amount=3000)

    resp = _apply(client, product, quantity=2)  # 2000 < 3000

    assert resp.status_code == 400
    body = resp.get_json()
    assert body['message'] == 'PRIMERACOMPRA requiere una compra mínima de $3.000: te faltan $1.000.'
    assert (body['reason'], body['missing'], body['waits']) == ('min_order', 1000, True)


def test_apply_coupon_accepts_exactly_at_min_order_amount(client, db):
    product = _create_product(db, price=1000)
    _create_coupon(db, discount_percent=10, min_order_amount=2000)

    resp = _apply(client, product, quantity=2)  # 2000 == 2000

    data = resp.get_json()
    assert data['ok'] is True
    assert data['discountAmount'] == 200


def test_min_order_amount_is_compared_after_the_2x1(client, db):
    product = _create_product(db, price=1000)
    promo = BundlePromo(label='2x1', buy_quantity=2, pay_quantity=1, is_active=True)
    db.session.add(promo)
    db.session.flush()
    promo.products = [product]
    db.session.commit()
    _create_coupon(db, discount_percent=10, min_order_amount=1500)

    resp = _apply(client, product, quantity=2)  # 2000 - 1000 (2x1) = 1000 < 1500

    assert resp.status_code == 400
    assert 'compra mínima' in resp.get_json()['message']


def test_min_order_amount_does_not_count_shipping(client, db):
    product = _create_product(db, price=1000)
    _create_coupon(db, discount_percent=10, min_order_amount=3000)
    _create_delivery_zone(db, price=1500)

    # 2000 of products + 1500 of shipping = 3500 - only reaches the minimum through shipping.
    resp = _apply(client, product, quantity=2, delivery_mode='envio', lat=-33.5, lng=-70.5)

    assert resp.status_code == 400
    assert 'compra mínima' in resp.get_json()['message']


def test_coupon_without_min_order_amount_has_no_minimum(client, db):
    product = _create_product(db, price=100)
    _create_coupon(db, discount_percent=10)

    resp = _apply(client, product, quantity=1)

    data = resp.get_json()
    assert data['ok'] is True
    assert data['discountAmount'] == 10


def test_create_order_enforces_min_order_amount_without_creating_order(client, db, order_payload):
    # The cart preview isn't the only gate - a direct POST must be rejected too.
    product = _create_product(db, price=1000)
    coupon = _create_coupon(db, discount_percent=10, min_order_amount=3000)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 2}], phone=PHONE, couponCode='primeracompra'))

    assert resp.status_code == 400
    assert 'compra mínima' in resp.get_json()['message']
    assert Order.query.count() == 0
    assert CouponRedemption.query.filter_by(coupon_id=coupon.id).count() == 0


# --- Panel: min_order_amount field ---

def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _post_coupon_form(client, **overrides):
    data = {'code': 'MINIMO', 'discount_percent': '10', 'scope': 'order'}
    data.update(overrides)
    return client.post('/admin/coupons/new', data=data, follow_redirects=True)


def test_panel_saves_min_order_amount(client, db):
    _register_owner(client)

    _post_coupon_form(client, min_order_amount='15000')

    coupon = Coupon.query.filter_by(code='MINIMO').one()
    assert coupon.min_order_amount == 15000
    assert coupon.kind == 'percent'


def test_panel_empty_min_order_amount_means_no_minimum(client, db):
    _register_owner(client)

    _post_coupon_form(client, min_order_amount='')

    assert Coupon.query.filter_by(code='MINIMO').one().min_order_amount is None


def test_panel_rejects_non_positive_min_order_amount(client, db):
    _register_owner(client)

    for bad in ('0', '-500', 'abc'):
        resp = _post_coupon_form(client, min_order_amount=bad)
        assert 'La compra mínima debe ser un monto mayor a 0'.encode() in resp.data
    assert Coupon.query.filter_by(code='MINIMO').count() == 0


# --- kind='fixed': a $ amount, capped at what it applies to ---

def _create_fixed_coupon(db, fixed_amount, **overrides):
    return _create_coupon(db, kind='fixed', discount_percent=None, fixed_amount=fixed_amount, **overrides)


def test_fixed_coupon_discounts_its_amount(client, db):
    product = _create_product(db, price=5000)
    _create_fixed_coupon(db, 2000)

    data = _apply(client, product, quantity=2).get_json()  # 10000

    assert data['ok'] is True
    assert data['kind'] == 'fixed'
    assert data['fixedAmount'] == 2000
    assert data['discountAmount'] == 2000


def test_fixed_coupon_bigger_than_cart_is_capped_and_never_leaves_negative_total(client, db, order_payload):
    product = _create_product(db, price=1000)
    _create_fixed_coupon(db, 5000)

    data = _apply(client, product, quantity=3).get_json()  # 3000
    assert data['discountAmount'] == 3000

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 3}], phone=PHONE, couponCode='primeracompra'))
    assert resp.get_json()['ok'] is True
    order = Order.query.one()
    assert order.discount_amount == 3000
    assert order.total_price == 0


def test_fixed_coupon_does_not_eat_shipping_by_default(client, db):
    product = _create_product(db, price=1000)
    _create_fixed_coupon(db, 5000)
    _create_delivery_zone(db, price=1500)

    data = _apply(client, product, quantity=2, delivery_mode='envio', lat=-33.5, lng=-70.5).get_json()

    assert data['discountAmount'] == 2000  # capped at products (2000); shipping still paid


def test_fixed_coupon_can_cover_shipping_when_flag_set(client, db):
    product = _create_product(db, price=1000)
    _create_fixed_coupon(db, 5000, applies_to_shipping=True)
    _create_delivery_zone(db, price=1500)

    data = _apply(client, product, quantity=2, delivery_mode='envio', lat=-33.5, lng=-70.5).get_json()

    assert data['discountAmount'] == 3500  # products (2000) + shipping (1500)


def test_fixed_coupon_products_scope_is_capped_at_those_products(client, db):
    target = _create_product(db, price=1000, name='Target')
    other = _create_product(db, price=5000, name='Other')
    coupon = _create_fixed_coupon(db, 3000, scope='products')
    coupon.products = [target]
    db.session.commit()

    resp = client.post('/api/apply-coupon', json={
        'code': 'primeracompra', 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': target.id, 'quantity': 2}, {'id': other.id, 'quantity': 1}],
    })

    assert resp.get_json()['discountAmount'] == 2000  # 2 x Target, not the 3000 nor Other's price


def test_fixed_coupon_respects_min_order_amount(client, db):
    product = _create_product(db, price=1000)
    _create_fixed_coupon(db, 2000, min_order_amount=5000)

    below = _apply(client, product, quantity=3)  # 3000 < 5000
    assert below.status_code == 400
    assert 'compra mínima' in below.get_json()['message']

    above = _apply(client, product, quantity=6)  # 6000 >= 5000
    assert above.get_json()['discountAmount'] == 2000


def test_banner_coupons_api_sends_kind_and_fixed_amount(client, db):
    _create_fixed_coupon(db, 2000, show_in_banner=True)

    payload = client.get('/api/banner-coupons').get_json()

    assert payload[0]['kind'] == 'fixed'
    assert payload[0]['fixedAmount'] == 2000
    assert payload[0]['discountPercent'] is None


# --- Panel: kind selector ---

def test_panel_creates_fixed_coupon_and_drops_any_percent(client, db):
    _register_owner(client)

    # discount_percent sent anyway (the JS disables it, but never trust the client).
    _post_coupon_form(client, kind='fixed', fixed_amount='2000', discount_percent='10')

    coupon = Coupon.query.filter_by(code='MINIMO').one()
    assert coupon.kind == 'fixed'
    assert coupon.fixed_amount == 2000
    assert coupon.discount_percent is None


def test_panel_rejects_fixed_coupon_without_positive_amount(client, db):
    _register_owner(client)

    for bad in ('', '0', '-100'):
        resp = _post_coupon_form(client, kind='fixed', fixed_amount=bad, discount_percent='')
        assert 'Ingresa un monto de descuento mayor a 0'.encode() in resp.data
    assert Coupon.query.filter_by(code='MINIMO').count() == 0


def test_panel_without_kind_still_creates_percent_coupon(client, db):
    _register_owner(client)

    _post_coupon_form(client)  # no 'kind' field at all

    coupon = Coupon.query.filter_by(code='MINIMO').one()
    assert coupon.kind == 'percent'
    assert coupon.discount_percent == 10
    assert coupon.fixed_amount is None


def test_panel_switching_kind_clears_the_other_value(client, db):
    _register_owner(client)
    coupon = _create_coupon(db, code='CAMBIA', discount_percent=15)

    client.post(f'/admin/coupons/{coupon.id}/edit', data={
        'code': 'CAMBIA', 'kind': 'fixed', 'fixed_amount': '3000', 'scope': 'order'})
    db.session.refresh(coupon)
    assert (coupon.kind, coupon.fixed_amount, coupon.discount_percent) == ('fixed', 3000, None)

    client.post(f'/admin/coupons/{coupon.id}/edit', data={
        'code': 'CAMBIA', 'kind': 'percent', 'discount_percent': '20', 'scope': 'order'})
    db.session.refresh(coupon)
    assert (coupon.kind, coupon.fixed_amount, coupon.discount_percent) == ('percent', None, 20)


def test_panel_rejects_unknown_kind(client, db):
    _register_owner(client)

    resp = _post_coupon_form(client, kind='bogus')

    assert 'el tipo de cupón'.encode() in resp.data
    assert Coupon.query.filter_by(code='MINIMO').count() == 0


def test_coupon_list_shows_fixed_amount_and_percent(client, db):
    _register_owner(client)
    _create_coupon(db, code='PORCIENTO', discount_percent=15)
    _create_fixed_coupon(db, 2500, code='FIJO')

    html = client.get('/admin/coupons').data.decode()

    assert '— 15% de descuento' in html
    assert '— $2500 de descuento' in html


def test_edit_form_preselects_fixed_kind_and_leaves_percent_empty(client, db):
    _register_owner(client)
    coupon = _create_fixed_coupon(db, 2000, code='FIJO')

    html = client.get(f'/admin/coupons/{coupon.id}/edit').data.decode()

    assert '<option value="fixed" selected>' in html
    assert 'name="fixed_amount" type="number" step="1" min="1" required\n               value="2000"' in html
    # A NULL percent must render empty, not "0" (None|int would).
    assert 'max="100" required\n               value=""' in html


# --- kind='product': gives a catalog product for $0 ---

def _create_gift_coupon(db, gift, **overrides):
    return _create_coupon(db, kind='product', discount_percent=None, gift_product_id=gift.id, **overrides)


def _create_stocked_product(db, name, price=2000, stock_quantity=None, **fields):
    product = _create_product(db, price=price, name=name)
    product.stock_quantity = stock_quantity
    for key, value in fields.items():
        setattr(product, key, value)
    db.session.commit()
    return product


def _gift_items(order):
    return OrderItem.query.filter_by(order_id=order.id, is_gift=True).all()


def test_apply_gift_coupon_discounts_nothing_and_names_the_gift(client, db):
    product = _create_product(db, price=5000)
    gift = _create_stocked_product(db, 'Postre')
    _create_gift_coupon(db, gift)

    data = _apply(client, product, quantity=1).get_json()

    assert data['ok'] is True
    assert data['kind'] == 'product'
    assert data['discountAmount'] == 0
    assert data['giftProductName'] == 'Postre'


def test_create_order_with_gift_coupon_adds_gift_item(client, db, order_payload):
    product = _create_product(db, price=5000)
    gift = _create_stocked_product(db, 'Postre', stock_quantity=4)
    coupon = _create_gift_coupon(db, gift)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='primeracompra'))

    assert resp.get_json()['ok'] is True
    order = Order.query.one()
    gifts = _gift_items(order)
    assert [(g.product_id, g.price, g.quantity) for g in gifts] == [(gift.id, 0, 1)]
    assert order.discount_amount == 0
    assert order.total_price == 5000
    assert order.coupon_id == coupon.id
    assert CouponRedemption.query.filter_by(coupon_id=coupon.id).count() == 1
    db.session.refresh(gift)
    assert gift.stock_quantity == 3


def test_gift_coupon_rejected_when_gift_unavailable(client, db):
    product = _create_product(db, price=5000)
    cases = [
        dict(name='Inactivo', is_active=False),
        dict(name='Agotado', sold_out=True),
        dict(name='SinStock', stock_quantity=0),
    ]
    for i, fields in enumerate(cases):
        gift = _create_stocked_product(db, **fields)
        _create_gift_coupon(db, gift, code=f'REGALO{i}')

        resp = client.post('/api/apply-coupon', json={
            'code': f'REGALO{i}', 'phone': PHONE, 'deliveryMode': 'retira',
            'items': [{'id': product.id, 'quantity': 1}],
        })

        assert resp.status_code == 400, fields
        assert resp.get_json()['message'] == f'El regalo de REGALO{i} ({gift.name}) no está disponible ahora.'
        assert resp.get_json()['reason'] == 'gift_unavailable'


def test_gift_coupon_replaces_the_automatic_threshold_gift(client, db, order_payload):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})
    product = _create_product(db, price=20000)
    auto_gift = _create_stocked_product(db, 'Regalo automatico')
    coupon_gift = _create_stocked_product(db, 'Regalo del cupon')
    owner = User.query.filter_by(is_owner=True).first()
    owner.gift_threshold_amount = 10000
    owner.gift_product_id = auto_gift.id
    db.session.commit()
    _create_gift_coupon(db, coupon_gift)

    client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='primeracompra'))

    gifts = _gift_items(Order.query.one())
    assert [g.product_id for g in gifts] == [coupon_gift.id]  # one gift, the coupon's


def test_automatic_gift_still_given_with_a_percent_coupon(client, db, order_payload):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})
    product = _create_product(db, price=20000)
    auto_gift = _create_stocked_product(db, 'Regalo automatico')
    owner = User.query.filter_by(is_owner=True).first()
    owner.gift_threshold_amount = 10000
    owner.gift_product_id = auto_gift.id
    db.session.commit()
    _create_coupon(db, discount_percent=10)

    client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='primeracompra'))

    assert [g.product_id for g in _gift_items(Order.query.one())] == [auto_gift.id]


def test_gift_coupon_rejected_when_cart_takes_the_last_units_of_the_gift(client, db, order_payload):
    # The gift is also in the cart: 2 in the cart + 1 gift needs 3, only 2 in stock.
    gift = _create_stocked_product(db, 'Postre', stock_quantity=2)
    _create_gift_coupon(db, gift)

    preview = _apply(client, gift, quantity=2)
    assert preview.status_code == 400
    assert 'no está disponible' in preview.get_json()['message']

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': gift.id, 'quantity': 2}], phone=PHONE, couponCode='primeracompra'))
    assert resp.status_code == 400
    assert Order.query.count() == 0
    db.session.refresh(gift)
    assert gift.stock_quantity == 2  # nothing was taken


def test_gift_coupon_accepted_when_stock_covers_cart_plus_gift(client, db, order_payload):
    gift = _create_stocked_product(db, 'Postre', stock_quantity=3)
    _create_gift_coupon(db, gift)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': gift.id, 'quantity': 2}], phone=PHONE, couponCode='primeracompra'))

    assert resp.get_json()['ok'] is True
    assert len(_gift_items(Order.query.one())) == 1
    db.session.refresh(gift)
    assert gift.stock_quantity == 0
    assert gift.sold_out is True


def test_gift_out_of_stock_at_checkout_saves_order_without_gift_or_coupon(client, db, order_payload, monkeypatch):
    # Safety net behind the validation above: force validation to pass, so the gift
    # is only found missing after the cart was decremented. The order must still be
    # saved - without the gift, and without spending the customer's coupon.
    monkeypatch.setattr(main_routes, '_coupon_gift_is_available', lambda coupon, order_lines: True)
    gift = _create_stocked_product(db, 'Postre', stock_quantity=2)
    coupon = _create_gift_coupon(db, gift)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': gift.id, 'quantity': 2}], phone=PHONE, couponCode='primeracompra'))

    assert resp.get_json()['ok'] is True
    order = Order.query.one()
    assert _gift_items(order) == []
    assert order.coupon_id is None
    assert CouponRedemption.query.filter_by(coupon_id=coupon.id).count() == 0


def test_gift_coupon_respects_min_order_amount(client, db):
    product = _create_product(db, price=1000)
    gift = _create_stocked_product(db, 'Postre')
    _create_gift_coupon(db, gift, min_order_amount=5000)

    below = _apply(client, product, quantity=3)
    assert below.status_code == 400
    assert 'compra mínima' in below.get_json()['message']

    assert _apply(client, product, quantity=5).get_json()['ok'] is True


def test_banner_shows_gift_coupon_only_while_gift_is_available(client, db):
    gift = _create_stocked_product(db, 'Postre', stock_quantity=1)
    _create_gift_coupon(db, gift, show_in_banner=True, min_order_amount=8000)

    payload = client.get('/api/banner-coupons').get_json()
    assert payload[0]['kind'] == 'product'
    assert payload[0]['giftProductName'] == 'Postre'
    assert payload[0]['minOrderAmount'] == 8000

    gift.stock_quantity = 0
    db.session.commit()
    assert client.get('/api/banner-coupons').get_json() == []


def test_panel_creates_gift_coupon_and_clears_discount_fields(client, db):
    _register_owner(client)
    gift = _create_stocked_product(db, 'Postre')
    other = _create_product(db, name='Otro')

    # Everything that doesn't apply to a gift is sent anyway - the server must drop it.
    _post_coupon_form(client, kind='product', gift_product_id=str(gift.id), discount_percent='10',
                      fixed_amount='2000', scope='products', product_ids=[str(other.id)],
                      applies_to_shipping='on')

    coupon = Coupon.query.filter_by(code='MINIMO').one()
    assert coupon.kind == 'product'
    assert coupon.gift_product_id == gift.id
    assert (coupon.discount_percent, coupon.fixed_amount) == (None, None)
    assert (coupon.scope, coupon.applies_to_shipping, coupon.products) == ('order', False, [])


def test_panel_gift_coupon_without_scope_field_is_accepted(client, db):
    # The form disables (so never sends) scope for a gift coupon.
    _register_owner(client)
    gift = _create_stocked_product(db, 'Postre')

    client.post('/admin/coupons/new', data={'code': 'REGALO', 'kind': 'product', 'gift_product_id': str(gift.id)})

    assert Coupon.query.filter_by(code='REGALO').one().scope == 'order'


def test_panel_rejects_gift_coupon_without_product(client, db):
    _register_owner(client)

    for bad in ('', '99999'):
        resp = _post_coupon_form(client, kind='product', gift_product_id=bad)
        assert 'Elige el producto que regala el cupón'.encode() in resp.data
    assert Coupon.query.filter_by(code='MINIMO').count() == 0


def test_panel_switching_gift_coupon_to_percent_drops_the_gift(client, db):
    _register_owner(client)
    gift = _create_stocked_product(db, 'Postre')
    coupon = _create_gift_coupon(db, gift, code='CAMBIA')

    client.post(f'/admin/coupons/{coupon.id}/edit', data={
        'code': 'CAMBIA', 'kind': 'percent', 'discount_percent': '10', 'scope': 'order'})

    db.session.refresh(coupon)
    assert (coupon.kind, coupon.gift_product_id, coupon.discount_percent) == ('percent', None, 10)


def test_coupon_list_shows_gift_product(client, db):
    _register_owner(client)
    gift = _create_stocked_product(db, 'Postre')
    _create_gift_coupon(db, gift, code='REGALO')

    html = client.get('/admin/coupons').data.decode()

    assert '— Regala: Postre' in html


def test_orders_panel_shows_gift_coupon_as_regalo_not_zero_discount(client, db, order_payload):
    _register_owner(client)
    product = _create_product(db, price=5000)
    gift = _create_stocked_product(db, 'Postre')
    _create_gift_coupon(db, gift, code='REGALO')
    client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='REGALO'))

    html = client.get('/admin/orders').data.decode()

    assert 'Cupón REGALO (regalo)' in html
    assert 'Descuento (REGALO): -$0' not in html
    assert '<span class="gift-badge">🎁 Regalo</span> Postre' in html


def test_editing_order_with_gift_coupon_keeps_one_gift_and_no_discount(client, db, order_payload):
    _register_owner(client)
    product = _create_product(db, price=5000)
    other = _create_product(db, price=1000, name='Otro')
    gift = _create_stocked_product(db, 'Postre')
    _create_gift_coupon(db, gift)
    client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='primeracompra'))
    order = Order.query.one()

    client.post(f'/admin/orders/{order.id}/items/add', data={'product_id': other.id, 'quantity': 1})

    db.session.refresh(order)
    assert order.discount_amount == 0
    assert order.total_price == 6000
    assert len(_gift_items(order)) == 1


def test_edit_form_preselects_gift_kind_and_product(client, db):
    _register_owner(client)
    gift = _create_stocked_product(db, 'Postre')
    coupon = _create_gift_coupon(db, gift, code='REGALO')

    html = client.get(f'/admin/coupons/{coupon.id}/edit').data.decode()

    assert '<option value="product" selected>' in html
    assert f'<option value="{gift.id}" selected>Postre</option>' in html
