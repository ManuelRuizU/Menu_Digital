"""create_order's response is the only source of amounts for the customer's WhatsApp
message: its breakdown, the expectedTotal drift check, and - end to end, through the
real order_message.js run by Node - that the message's total equals the saved total_price."""
import json
import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models import BundlePromo, BundlePromoTier, Category, Coupon, Order, Product, User

PHONE = '56911112222'
JS_RENDER = Path(__file__).parent / 'js' / 'render_whatsapp.js'


def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _product(db, name, price):
    category = Category.query.first()
    if category is None:
        category = Category(name='Carta')
        db.session.add(category)
        db.session.commit()
    product = Product(name=name, description='T', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


def _tiered(db, products, label='Hand rolls'):
    promo = BundlePromo(label=label, kind='tiered', is_active=True,
                        tiers=[BundlePromoTier(quantity=2, total_price=4990), BundlePromoTier(quantity=3, total_price=6990)])
    db.session.add(promo)
    db.session.flush()
    promo.products = products
    db.session.commit()


def _two_for_one(db, products, label='2x1 bebidas'):
    promo = BundlePromo(label=label, kind='buy_pay', buy_quantity=2, pay_quantity=1, is_active=True)
    db.session.add(promo)
    db.session.flush()
    promo.products = products
    db.session.commit()


def _post_order(client, order_payload, items, **extra):
    resp = client.post('/api/orders', json=order_payload(items=items, phone=PHONE, **extra))
    data = resp.get_json()
    assert data['ok'] is True, data
    return data


def _scenario_tiered(client, db, order_payload):
    roll = _product(db, 'Hand roll pollo', 2990)
    _tiered(db, [roll])
    return _post_order(client, order_payload, [{'id': roll.id, 'quantity': 3}])


def _scenario_two_for_one(client, db, order_payload):
    bebida = _product(db, 'Jugo', 1500)
    _two_for_one(db, [bebida])
    return _post_order(client, order_payload, [{'id': bebida.id, 'quantity': 2}])


def _scenario_both(client, db, order_payload):
    roll = _product(db, 'Hand roll pollo', 2990)
    bebida = _product(db, 'Jugo', 1500)
    _tiered(db, [roll])
    _two_for_one(db, [bebida])
    return _post_order(client, order_payload, [{'id': roll.id, 'quantity': 2}, {'id': bebida.id, 'quantity': 2}])


def _scenario_with_coupon(client, db, order_payload):
    roll = _product(db, 'Hand roll pollo', 2990)
    _tiered(db, [roll])
    db.session.add(Coupon(code='DIEZ', kind='percent', discount_percent=10, scope='order', is_active=True))
    db.session.commit()
    return _post_order(client, order_payload, [{'id': roll.id, 'quantity': 3}], couponCode='DIEZ')


def _scenario_with_gift(client, db, order_payload):
    _register_owner(client)
    roll = _product(db, 'Hand roll pollo', 2990)
    mochi = _product(db, 'Mochi', 2000)
    _tiered(db, [roll])
    owner = User.query.filter_by(is_owner=True).first()
    owner.gift_threshold_amount = 5000
    owner.gift_product_id = mochi.id
    db.session.commit()
    return _post_order(client, order_payload, [{'id': roll.id, 'quantity': 3}])


def _scenario_with_gift_coupon(client, db, order_payload):
    roll = _product(db, 'Hand roll pollo', 2990)
    mochi = _product(db, 'Mochi', 2000)
    _tiered(db, [roll])
    db.session.add(Coupon(code='REGALO', kind='product', gift_product_id=mochi.id, scope='order', is_active=True))
    db.session.commit()
    return _post_order(client, order_payload, [{'id': roll.id, 'quantity': 2}], couponCode='REGALO')


SCENARIOS = {
    'tiered': _scenario_tiered,
    '2x1': _scenario_two_for_one,
    'tiered + 2x1': _scenario_both,
    'tiered + cupón %': _scenario_with_coupon,
    'tiered + regalo': _scenario_with_gift,
    'tiered + cupón regalo': _scenario_with_gift_coupon,
}


# --- the response itself ---

def test_create_order_response_has_the_full_breakdown(client, db, order_payload):
    data = _scenario_both(client, db, order_payload)

    order = Order.query.one()
    assert data['orderId'] == order.id
    assert data['subtotal'] == 2 * 2990 + 2 * 1500
    assert data['shipping'] == 0
    assert sorted((p['label'], p['amount']) for p in data['promos']) == [('2x1 bebidas', 1500), ('Hand rolls', 990)]
    assert data['coupon'] is None and data['gift'] is None
    assert data['total'] == order.total_price == 8980 - 990 - 1500
    assert data['lines'] == [
        {'name': 'Hand roll pollo', 'quantity': 2, 'options': [], 'total': 5980},
        {'name': 'Jugo', 'quantity': 2, 'options': [], 'total': 3000},
    ]


def test_response_reports_the_coupon(client, db, order_payload):
    data = _scenario_with_coupon(client, db, order_payload)

    assert data['coupon'] == {'code': 'DIEZ', 'kind': 'percent', 'amount': 699}


def test_response_reports_the_threshold_gift(client, db, order_payload):
    data = _scenario_with_gift(client, db, order_payload)

    assert data['gift'] == {'name': 'Mochi', 'couponCode': None, 'threshold': 5000}


def test_response_carries_the_whatsapp_number(client, db, order_payload):
    _register_owner(client)
    owner = User.query.filter_by(is_owner=True).first()
    owner.whatsapp_number = '56987654321'
    db.session.commit()
    product = _product(db, 'Roll', 2990)

    data = _post_order(client, order_payload, [{'id': product.id, 'quantity': 1}])

    assert data['whatsappNumber'] == '56987654321'


# --- expectedTotal: only compared, only logged ---

def test_expected_total_mismatch_logs_a_warning_with_both_amounts(client, db, order_payload, caplog):
    product = _product(db, 'Roll', 2990)

    with caplog.at_level(logging.WARNING):
        data = _post_order(client, order_payload, [{'id': product.id, 'quantity': 1}], expectedTotal=2500)

    order = Order.query.one()
    assert order.total_price == 2990  # never priced from the client's number
    assert f'Order {order.id}: cart preview total 2500 != server total 2990' in caplog.text
    assert data['total'] == 2990


@pytest.mark.parametrize('expected', [2990, None])
def test_matching_or_missing_expected_total_logs_nothing(client, db, order_payload, caplog, expected):
    product = _product(db, 'Roll', 2990)
    extra = {} if expected is None else {'expectedTotal': expected}

    with caplog.at_level(logging.WARNING):
        _post_order(client, order_payload, [{'id': product.id, 'quantity': 1}], **extra)

    assert 'cart preview total' not in caplog.text


# --- end to end: the real WhatsApp text vs the saved total_price ---

def _clp(amount):
    return '$' + f'{amount:,}'.replace(',', '.')


@pytest.mark.parametrize('name', list(SCENARIOS))
def test_whatsapp_total_equals_saved_total_price(client, db, order_payload, tmp_path, name):
    node = shutil.which('node')
    if node is None:
        pytest.skip('WhatsApp text NOT verified: node not found - run where Node is installed')

    data = SCENARIOS[name](client, db, order_payload)
    order = Order.query.one()
    customer = {'name': 'Ana', 'phone': PHONE, 'deliveryMode': 'retira', 'address': '', 'paymentLabel': 'Efectivo',
                'paymentMethod': 'efectivo', 'cashAmount': 0, 'requestedTimeLabel': '19:00', 'notes': ''}
    scenario_file = tmp_path / 'scenario.json'
    scenario_file.write_text(json.dumps([{'order': data, 'customer': customer}]), encoding='utf-8')

    result = subprocess.run([node, str(JS_RENDER), str(scenario_file)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    text = json.loads(result.stdout)[0]

    assert f'Total: {_clp(order.total_price)}' in text
    for promo in data['promos']:
        assert f"{promo['label']}: -{_clp(promo['amount'])}" in text
    if name == 'tiered + regalo':
        assert '• 1× Mochi - de regalo 🎁 (por compra sobre $5.000)' in text
    if name == 'tiered + cupón regalo':
        assert '• 1× Mochi - de regalo 🎁 (cupón REGALO)' in text
        assert 'Descuento (REGALO)' not in text
