"""Coupon adoption: why a code was rejected (and what the customer reads), the cart's
coupon card (/api/cart-coupons), and the attempt log behind the panel's "Uso de cupones"."""
from datetime import date, datetime, timedelta

from app.coupon_attempts import log_attempt, purge_old, usage_summary
from app.models import BUSINESS_TZ, Category, Coupon, CouponAttempt, CouponRedemption, Order, Product

PHONE = '56911112222'


def _product(db, price=1000, name='Roll'):
    category = Category.query.first() or Category(name='Sushi')
    db.session.add(category)
    db.session.commit()
    product = Product(name=name, description='', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


def _coupon(db, code='DULCE', **fields):
    values = dict(code=code, discount_percent=10, scope='order', is_active=True, show_in_banner=True)
    values.update(fields)
    coupon = Coupon(**values)
    db.session.add(coupon)
    db.session.commit()
    return coupon


def _today():
    return datetime.now(BUSINESS_TZ).date()


def _apply(client, product, code='DULCE', quantity=1, **extra):
    return client.post('/api/apply-coupon', json={
        'code': code, 'phone': PHONE, 'deliveryMode': 'retira',
        'items': [{'id': product.id, 'quantity': quantity}], **extra})


def _cart(client, product, quantity=1, phone=PHONE):
    return client.post('/api/cart-coupons', json={
        'phone': phone, 'deliveryMode': 'retira', 'items': [{'id': product.id, 'quantity': quantity}]}).get_json()


# --- rejection reasons and messages ---

def test_each_rejection_has_a_reason_and_a_clear_message(client, db):
    product = _product(db, price=4000)
    yesterday, tomorrow = _today() - timedelta(days=1), _today() + timedelta(days=1)
    _coupon(db, code='VENCIDO', valid_until=yesterday)
    _coupon(db, code='PRONTO', valid_from=tomorrow)
    _coupon(db, code='AGOTADO', max_total_uses=0)
    _coupon(db, code='MINIMO', min_order_amount=10000)

    cases = {
        'nadaque': ('not_found', 'No encontramos el código «NADAQUE». Revisa que esté bien escrito.', False),
        'vencido': ('expired', f'El código VENCIDO venció el {yesterday.strftime("%d/%m")}.', False),
        'pronto': ('not_yet', f'El código PRONTO empieza a funcionar el {tomorrow.strftime("%d/%m")}.', False),
        'agotado': ('exhausted', 'El código AGOTADO ya se agotó.', False),
        'minimo': ('min_order', 'MINIMO requiere una compra mínima de $10.000: te faltan $6.000.', True),
    }
    for code, (reason, message, waits) in cases.items():
        body = _apply(client, product, code=code).get_json()
        assert (body['ok'], body['reason'], body['message'], body['waits']) == (False, reason, message, waits), code


def test_already_used_is_a_thank_you(client, db, order_payload):
    product = _product(db)
    _coupon(db, max_uses_per_customer=1)
    assert client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], phone=PHONE, couponCode='DULCE')).get_json()['ok']

    body = _apply(client, product).get_json()
    assert body['reason'] == 'already_used'
    assert body['message'] == 'Ya usaste DULCE en un pedido anterior; ¡gracias por volver!'


def test_per_customer_coupon_asks_for_the_phone(client, db):
    product = _product(db)
    _coupon(db, max_uses_per_customer=1)
    body = _apply(client, product, phone='').get_json()
    assert (body['reason'], body['message']) == ('phone_required', 'Escribe tu teléfono para usar el código DULCE.')


# --- the coupon card ---

def test_cart_coupons_lists_public_ones_biggest_saving_first(client, db):
    product = _product(db, price=5000)
    gift = _product(db, price=2500, name='Té helado')
    _coupon(db, code='DIEZ', discount_percent=10)                          # $500
    _coupon(db, code='VEINTE', discount_percent=20)                        # $1.000
    _coupon(db, code='REGALO', kind='product', discount_percent=None, gift_product_id=gift.id)  # worth $2.500
    _coupon(db, code='GRANDE', discount_percent=30, min_order_amount=8000)  # short by $3.000
    _coupon(db, code='SECRETO', discount_percent=50, show_in_banner=False)
    _coupon(db, code='VIEJO', discount_percent=50, valid_until=_today() - timedelta(days=1))

    offers = _cart(client, product)['coupons']

    assert [o['code'] for o in offers] == ['REGALO', 'VEINTE', 'DIEZ', 'GRANDE']
    assert [o['saving'] for o in offers] == [2500, 1000, 500, 0]
    assert offers[0]['description'] == 'Llévate gratis Té helado'
    assert offers[1]['description'] == '20% de descuento en tu pedido'
    assert (offers[3]['status'], offers[3]['missing']) == ('min_order', 3000)


def test_cart_coupons_hides_what_this_phone_already_used(client, db, order_payload):
    product = _product(db)
    _coupon(db, max_uses_per_customer=1)
    assert _cart(client, product, phone='')['coupons'][0]['needsPhone'] is True
    client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 1}], phone=PHONE,
                                                  couponCode='DULCE'))
    assert _cart(client, product)['coupons'] == []
    assert _cart(client, product, phone='56999998888')['coupons'][0]['needsPhone'] is False


def test_cart_coupons_with_an_empty_cart_is_empty(client, db):
    _coupon(db)
    resp = client.post('/api/cart-coupons', json={'items': []})
    assert resp.get_json() == {'ok': True, 'coupons': []}


# --- the attempt log ---

def test_customer_attempts_are_logged_rechecks_are_not(client, db):
    product = _product(db, price=4000)
    _coupon(db, min_order_amount=5000)

    _apply(client, product, source='manual')                    # short: rejected
    _apply(client, product, quantity=2, source='card')          # applies
    _apply(client, product, quantity=2)                         # the menu re-checking: no source
    _apply(client, product, quantity=2, source='hacker')        # unknown source: not logged
    _apply(client, product, code='nada', source='banner')       # unknown code: counted

    rows = [(r.code, r.source, r.result, r.reason) for r in CouponAttempt.query.order_by(CouponAttempt.id)]
    assert rows == [('DULCE', 'manual', 'rejected', 'min_order'), ('DULCE', 'card', 'applied', None),
                    ('NADA', 'banner', 'rejected', 'not_found')]


def test_order_logs_the_coupon_use_with_its_source(client, db, order_payload):
    product = _product(db)
    _coupon(db)
    client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 1}],
                                                  couponCode='DULCE', couponSource='reminder'))
    client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 1}], phone='56922223333',
                                                  couponCode='DULCE'))  # a page older than the log
    client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 1}]))  # no coupon
    rows = [(r.code, r.source, r.result) for r in CouponAttempt.query.order_by(CouponAttempt.id)]
    assert rows == [('DULCE', 'reminder', 'used'), ('DULCE', None, 'used')]
    assert Order.query.count() == 3


def test_coupon_event_only_logs_reminder_results_of_real_coupons(client, db):
    _coupon(db)
    assert client.post('/api/coupon-event', json={'code': 'dulce', 'result': 'shown'}).status_code == 200
    assert client.post('/api/coupon-event', json={'code': 'DULCE', 'result': 'declined'}).status_code == 200
    assert client.post('/api/coupon-event', json={'code': 'DULCE', 'result': 'used'}).status_code == 400
    assert client.post('/api/coupon-event', json={'code': 'INVENTADO', 'result': 'shown'}).status_code == 400
    rows = [(r.code, r.source, r.result) for r in CouponAttempt.query.order_by(CouponAttempt.id)]
    assert rows == [('DULCE', 'reminder', 'shown'), ('DULCE', 'reminder', 'declined')]


def test_log_keeps_no_personal_data_and_cuts_long_codes(db):
    assert log_attempt('  x' * 40, 'manual', 'rejected', 'not_found')
    assert not log_attempt('', 'manual', 'applied')
    assert not log_attempt('DULCE', 'manual', 'borrado')
    row = CouponAttempt.query.one()
    assert len(row.code) == 30
    assert {c.name for c in CouponAttempt.__table__.columns} == {'id', 'code', 'source', 'result', 'reason', 'created_at'}


def test_usage_summary_and_purge(db):
    for source, result, reason in [('card', 'applied', None), ('card', 'used', None), ('manual', 'rejected', 'expired'),
                                   ('reminder', 'shown', None), ('reminder', 'declined', None)]:
        log_attempt('DULCE', source, result, reason)
    log_attempt('OTRO', 'manual', 'rejected', 'not_found')
    old = CouponAttempt(code='VIEJO', source='manual', result='applied', created_at=datetime.utcnow() - timedelta(days=200))
    db.session.add(old)
    db.session.commit()

    summary = usage_summary(30)
    assert [entry['code'] for entry in summary['codes']] == ['DULCE', 'OTRO']
    dulce = summary['codes'][0]
    assert dulce['by_source']['card'] == {'applied': 1, 'used': 1}
    assert dulce['rejected_by_reason'] == {'expired': 1}
    assert summary['reminder'] == {'shown': 1, 'declined': 1}

    assert purge_old() == 1
    assert CouponAttempt.query.filter_by(code='VIEJO').count() == 0


def test_usage_panel_is_for_the_owner(client, db):
    assert client.get('/admin/coupons/usage').status_code == 302
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})
    log_attempt('DULCE', 'banner', 'applied')
    html = client.get('/admin/coupons/usage?days=7').get_data(as_text=True)
    assert 'Uso de cupones' in html and 'DULCE' in html and 'Banner' in html
    assert 'href="/admin/coupons/usage"' in client.get('/admin/coupons').get_data(as_text=True)


# --- the menu page ---

def test_menu_has_the_coupon_box_reminder_and_banner_button(client, db):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})
    _coupon(db)
    html = client.get('/').get_data(as_text=True)
    assert 'id="coupon-offers"' in html and 'id="coupon-box"' in html
    assert 'id="coupon-reminder"' in html and 'Aplicar y enviar' in html and 'Enviar sin cupón' in html
    assert 'Usar cupón' in html and 'Usar código' not in html
    assert html.index('coupon_ui.js') < html.index('menu.js')
