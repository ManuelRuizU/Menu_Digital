import json

from app.models import BundlePromo, Category, DeliveryZone, Order, Product


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


def _create_promo(db, products, buy_quantity=2, pay_quantity=1, **overrides):
    promo = BundlePromo(label='Promo', buy_quantity=buy_quantity, pay_quantity=pay_quantity,
                         is_active=True, **overrides)
    db.session.add(promo)
    db.session.flush()
    promo.products = products
    db.session.commit()
    return promo


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


def test_2x1_across_two_different_products_frees_the_cheaper_one(client, db, order_payload):
    expensive = _create_product(db, price=5000, name='Caro')
    cheap = _create_product(db, price=3000, name='Barato')
    _create_promo(db, [expensive, cheap], buy_quantity=2, pay_quantity=1)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': expensive.id, 'quantity': 1}, {'id': cheap.id, 'quantity': 1}], phone=PHONE))
    data = resp.get_json()
    assert data['ok'] is True
    order = Order.query.order_by(Order.id.desc()).first()
    assert order.bundle_discount_amount == 3000
    assert order.total_price == 5000  # 8000 - 3000 free


def test_3x2_frees_cheapest_of_three(client, db, order_payload):
    a = _create_product(db, price=4000, name='A')
    b = _create_product(db, price=3000, name='B')
    c = _create_product(db, price=2000, name='C')
    _create_promo(db, [a, b, c], buy_quantity=3, pay_quantity=2)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': a.id, 'quantity': 1}, {'id': b.id, 'quantity': 1}, {'id': c.id, 'quantity': 1}], phone=PHONE))
    order = Order.query.order_by(Order.id.desc()).first()
    assert order.bundle_discount_amount == 2000
    assert order.total_price == 7000  # 9000 - 2000 free


def test_incomplete_group_gets_no_discount(client, db, order_payload):
    product = _create_product(db, price=1000, name='Solo')
    _create_promo(db, [product], buy_quantity=2, pay_quantity=1)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE))  # only 1, needs 2
    order = Order.query.order_by(Order.id.desc()).first()
    assert order.bundle_discount_amount == 0
    assert order.total_price == 1000


def test_two_full_groups_both_get_cheapest_free(client, db, order_payload):
    product = _create_product(db, price=1000, name='Unico')
    _create_promo(db, [product], buy_quantity=2, pay_quantity=1)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 4}], phone=PHONE))  # 2 complete groups of 2
    order = Order.query.order_by(Order.id.desc()).first()
    assert order.bundle_discount_amount == 2000  # 2 free units at $1000 each
    assert order.total_price == 2000  # pays for 2 of the 4


def test_promo_ignores_products_not_in_its_list(client, db, order_payload):
    eligible = _create_product(db, price=1000, name='Elegible')
    other = _create_product(db, price=5000, name='Otro')
    _create_promo(db, [eligible], buy_quantity=2, pay_quantity=1)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': eligible.id, 'quantity': 1}, {'id': other.id, 'quantity': 1}], phone=PHONE))
    order = Order.query.order_by(Order.id.desc()).first()
    assert order.bundle_discount_amount == 0  # only 1 eligible unit, needs 2
    assert order.total_price == 6000


def test_inactive_promo_does_not_apply(client, db, order_payload):
    product = _create_product(db, price=1000, name='Inactivo')
    promo = _create_promo(db, [product], buy_quantity=2, pay_quantity=1)
    promo.is_active = False
    db.session.commit()

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 2}], phone=PHONE))
    order = Order.query.order_by(Order.id.desc()).first()
    assert order.bundle_discount_amount == 0
    assert order.total_price == 2000


def test_bundle_discount_never_touches_shipping_cost(client, db, order_payload):
    product = _create_product(db, price=1000, name='Unico')
    _create_promo(db, [product], buy_quantity=2, pay_quantity=1)
    _create_delivery_zone(db, price=1500)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 2}], phone=PHONE,  # triggers the 2x1
        deliveryMode='envio', address='Calle Falsa 123', lat=-33.5, lng=-70.5))
    order = Order.query.order_by(Order.id.desc()).first()
    assert order.bundle_discount_amount == 1000  # 1 free unit at $1000
    assert order.shipping_cost == 1500  # untouched by the bundle discount
    assert order.total_price == 2500  # 2000 (subtotal) + 1500 (shipping) - 1000 (bundle discount)
