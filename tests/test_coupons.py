import json
from datetime import date, timedelta

from app.models import Category, Coupon, CouponRedemption, DeliveryZone, Order, Product


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
