"""kind='tiered' BundlePromo: "hand roll $2.990, 2 por $4.990, 3 por $6.990", mixing any
hand roll of the promo. Python is the source of truth; menu.js mirrors it (own layer)."""
import json
import logging
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.main.routes import compute_bundle_discount, tiered_cost_for_units, tiered_discount_for_units
from app.models import (BundlePromo, BundlePromoTier, Category, Coupon, Order, OrderItem, OrderItemOption,
                        Product, ProductOption, ProductOptionGroup)

PHONE = '56911112222'
UNIT = 2990


def _create_product(db, name='Hand roll pollo', price=UNIT):
    category = Category.query.first()
    if category is None:
        category = Category(name='Hand rolls')
        db.session.add(category)
        db.session.commit()
    product = Product(name=name, description='Test', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


def _create_tiered_promo(db, products, tiers=((2, 4990), (3, 6990)), label='Hand rolls', **overrides):
    fields = {'is_active': True, **overrides}
    promo = BundlePromo(label=label, kind='tiered', **fields)
    promo.tiers = [BundlePromoTier(quantity=q, total_price=price) for q, price in tiers]
    db.session.add(promo)
    db.session.flush()
    promo.products = products
    db.session.commit()
    return promo


def _line(product, quantity, options=(), unit_price=None):
    options = list(options)
    if unit_price is None:
        unit_price = product.price + sum(o.price_delta for o in options)
    return (product, quantity, options, unit_price)


# --- the dynamic-programming price, on its own ---

TESTS_DIR = Path(__file__).parent
SHARED_CASES = json.loads((TESTS_DIR / 'fixtures' / 'tiered_cases.json').read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', SHARED_CASES, ids=[c['name'] for c in SHARED_CASES])
def test_shared_tiered_vectors(case):
    """Same file the JS tests read - the menu's mirror and this can't drift apart."""
    tiers = [tuple(tier) for tier in case['tiers']]
    assert tiered_cost_for_units(case['unit'], tiers, case['n']) == case['expected_cost']
    assert tiered_discount_for_units(case['unit'], tiers, case['n']) == case['expected_discount']


def test_js_mirror_passes_the_same_vectors():
    """Runs tests/js with Node's built-in runner so a plain `pytest` also covers the JS."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed - run `node --test tests/js` where it is')
    result = subprocess.run([node, '--test', str(TESTS_DIR / 'js')], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('units, expected_discount', [
    (1, 0),                       # 2990 alone
    (2, 2 * UNIT - 4990),         # 2 por 4990 -> 990
    (3, 3 * UNIT - 6990),         # 3 por 6990 -> 1980
    (4, 4 * UNIT - 9980),         # 3+1 = 2+2 = 9980 -> 1980
    (7, 7 * UNIT - 16970),        # 3+3+1 = 3+2+2 = 16970 (2+2+2+1 = 17960 is worse) -> 3960
])
def test_tiered_discount_by_number_of_units(client, db, units, expected_discount):
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])

    assert compute_bundle_discount([_line(product, units)], [promo]) == expected_discount


def test_tiered_promo_mixes_different_products_of_the_promo(client, db):
    pollo = _create_product(db, 'Hand roll pollo')
    camaron = _create_product(db, 'Hand roll camarón')
    salmon = _create_product(db, 'Hand roll salmón')
    promo = _create_tiered_promo(db, [pollo, camaron, salmon])

    lines = [_line(pollo, 1), _line(camaron, 1), _line(salmon, 1)]

    assert compute_bundle_discount(lines, [promo]) == 3 * UNIT - 6990


def test_products_outside_the_promo_are_not_counted(client, db):
    hand_roll = _create_product(db)
    bebida = _create_product(db, 'Bebida', price=UNIT)  # same price, but not in the promo
    promo = _create_tiered_promo(db, [hand_roll])

    lines = [_line(hand_roll, 1), _line(bebida, 1)]

    assert compute_bundle_discount(lines, [promo]) == 0


def test_variant_surcharge_is_charged_in_full_never_discounted(client, db):
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])
    extra = SimpleNamespace(price_delta=500)  # e.g. "Extra palta +$500"

    # One plain + one with the +$500 variant: the tier prices the two bases (4990 for 2),
    # the variant's 500 stays on top -> discount is only on the base: 5980 - 4990.
    lines = [_line(product, 1), _line(product, 1, [extra])]

    assert compute_bundle_discount(lines, [promo]) == 2 * UNIT - 4990


def test_tier_that_costs_more_than_singles_never_applies(client, db):
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product], tiers=((2, 6500),))  # 2 x 2990 = 5980 is cheaper

    assert compute_bundle_discount([_line(product, 2)], [promo]) == 0


def test_tiered_promo_skipped_with_log_when_prices_no_longer_match(client, db, caplog):
    a = _create_product(db, 'Hand roll pollo', price=UNIT)
    b = _create_product(db, 'Hand roll premium', price=UNIT)
    promo = _create_tiered_promo(db, [a, b])
    b.price = 3490  # edited after the promo was set up
    db.session.commit()

    with caplog.at_level(logging.WARNING):
        discount = compute_bundle_discount([_line(a, 1), _line(b, 1)], [promo])

    assert discount == 0
    assert 'no longer share one base price' in caplog.text


def test_unknown_kind_gives_no_discount_and_logs_instead_of_raising(client, db, caplog):
    product = _create_product(db)
    # Can't be stored (CHECK constraint) - simulates a malformed promo reaching the code.
    weird = SimpleNamespace(label='Rara', kind='bogus', products=[product], tiers=[])

    with caplog.at_level(logging.WARNING):
        discount = compute_bundle_discount([_line(product, 3)], [weird])

    assert discount == 0
    assert "unknown kind 'bogus'" in caplog.text


def test_buy_pay_and_tiered_promos_on_different_products_add_up(client, db):
    hand_roll = _create_product(db)
    bebida = _create_product(db, 'Bebida', price=1500)
    tiered = _create_tiered_promo(db, [hand_roll])
    two_for_one = BundlePromo(label='2x1 bebidas', kind='buy_pay', buy_quantity=2, pay_quantity=1, is_active=True)
    db.session.add(two_for_one)
    db.session.flush()
    two_for_one.products = [bebida]
    db.session.commit()

    lines = [_line(hand_roll, 3), _line(bebida, 2)]

    assert compute_bundle_discount(lines, [tiered, two_for_one]) == (3 * UNIT - 6990) + 1500


# --- end to end through create_order / apply-coupon ---

def _order(client, order_payload, items, **extra):
    return client.post('/api/orders', json=order_payload(items=items, phone=PHONE, **extra))


def test_create_order_stores_tiered_discount_in_bundle_discount_amount(client, db, order_payload):
    pollo = _create_product(db, 'Hand roll pollo')
    salmon = _create_product(db, 'Hand roll salmón')
    _create_tiered_promo(db, [pollo, salmon])

    resp = _order(client, order_payload, [{'id': pollo.id, 'quantity': 2}, {'id': salmon.id, 'quantity': 1}])

    assert resp.get_json()['ok'] is True
    order = Order.query.one()
    assert order.bundle_discount_amount == 3 * UNIT - 6990
    assert order.total_price == 6990


def test_create_order_with_variant_charges_the_surcharge_on_top(client, db, order_payload):
    product = _create_product(db)
    _create_tiered_promo(db, [product])
    group = ProductOptionGroup(product_id=product.id, name='Extras', required=False, multi_select=True)
    db.session.add(group)
    db.session.flush()
    extra = ProductOption(group_id=group.id, name='Extra palta', price_delta=500)
    db.session.add(extra)
    db.session.commit()

    _order(client, order_payload, [{'id': product.id, 'quantity': 1},
                                   {'id': product.id, 'quantity': 1, 'options': [extra.id]}])

    order = Order.query.one()
    assert order.total_price == 4990 + 500


@pytest.mark.parametrize('overrides', [
    {'is_active': False},
    {'valid_until': date.today() - timedelta(days=2)},
    {'valid_from': date.today() + timedelta(days=2)},
])
def test_inactive_or_out_of_date_tiered_promo_does_not_apply(client, db, order_payload, overrides):
    product = _create_product(db)
    _create_tiered_promo(db, [product], **overrides)

    _order(client, order_payload, [{'id': product.id, 'quantity': 3}])

    order = Order.query.one()
    assert order.bundle_discount_amount == 0
    assert order.total_price == 3 * UNIT


def test_percent_coupon_applies_after_the_tiered_promo(client, db, order_payload):
    product = _create_product(db)
    _create_tiered_promo(db, [product])
    db.session.add(Coupon(code='DIEZ', kind='percent', discount_percent=10, scope='order', is_active=True))
    db.session.commit()

    preview = client.post('/api/apply-coupon', json={
        'code': 'DIEZ', 'phone': PHONE, 'deliveryMode': 'retira', 'items': [{'id': product.id, 'quantity': 3}]})
    assert preview.get_json()['discountAmount'] == 699  # 10% of 6990, not of 8970

    _order(client, order_payload, [{'id': product.id, 'quantity': 3}], couponCode='DIEZ')
    order = Order.query.one()
    assert (order.bundle_discount_amount, order.discount_amount, order.total_price) == (1980, 699, 6990 - 699)


def test_fixed_coupon_applies_after_the_tiered_promo(client, db, order_payload):
    product = _create_product(db)
    _create_tiered_promo(db, [product])
    db.session.add(Coupon(code='DOSMIL', kind='fixed', fixed_amount=2000, scope='order', is_active=True))
    db.session.commit()

    _order(client, order_payload, [{'id': product.id, 'quantity': 3}], couponCode='DOSMIL')

    order = Order.query.one()
    assert (order.bundle_discount_amount, order.discount_amount, order.total_price) == (1980, 2000, 4990)


def test_coupon_min_order_is_compared_after_the_tiered_promo(client, db):
    product = _create_product(db)
    _create_tiered_promo(db, [product])
    db.session.add(Coupon(code='MIN', kind='percent', discount_percent=10, scope='order',
                          is_active=True, min_order_amount=8000))
    db.session.commit()

    # 3 units: 8970 before the promo, 6990 after -> below the 8000 minimum.
    resp = client.post('/api/apply-coupon', json={
        'code': 'MIN', 'phone': PHONE, 'deliveryMode': 'retira', 'items': [{'id': product.id, 'quantity': 3}]})

    assert resp.status_code == 400
    assert 'compra mínima' in resp.get_json()['message']


# --- edited orders (panel): snapshot prices, gifts excluded ---

def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _saved_order(db, lines):
    order = Order(customer_name='Cliente', phone=PHONE, delivery_mode='retira', payment_method='efectivo',
                  shipping_cost=0, total_price=0, status='Pending')
    db.session.add(order)
    db.session.flush()
    for product, quantity, price, is_gift, option_deltas in lines:
        item = OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                         quantity=quantity, price=price, is_gift=is_gift)
        db.session.add(item)
        db.session.flush()
        for delta in option_deltas:
            db.session.add(OrderItemOption(order_item_id=item.id, name='Extra', price_delta=delta))
    db.session.commit()
    return order


def test_gift_unit_does_not_count_toward_a_tier_when_editing(client, db):
    _register_owner(client)
    hand_roll = _create_product(db)
    other = _create_product(db, 'Bebida', price=1000)
    _create_tiered_promo(db, [hand_roll])
    # 1 paid hand roll + 1 gifted one: only 1 paid unit, so no "2 por" tier.
    order = _saved_order(db, [(hand_roll, 1, UNIT, False, []), (hand_roll, 1, 0, True, [])])

    client.post(f'/admin/orders/{order.id}/items/add', data={'product_id': other.id, 'quantity': 1})

    db.session.refresh(order)
    assert order.bundle_discount_amount == 0
    assert order.total_price == UNIT + 1000


def test_editing_order_takes_variants_out_of_the_snapshot_price(client, db):
    _register_owner(client)
    hand_roll = _create_product(db)
    other = _create_product(db, 'Bebida', price=1000)
    _create_tiered_promo(db, [hand_roll])
    # Two hand rolls saved at checkout, one with a +500 variant (snapshot price 3490).
    order = _saved_order(db, [(hand_roll, 1, UNIT, False, []), (hand_roll, 1, UNIT + 500, False, [500])])

    client.post(f'/admin/orders/{order.id}/items/add', data={'product_id': other.id, 'quantity': 1})

    db.session.refresh(order)
    assert order.bundle_discount_amount == 2 * UNIT - 4990
    assert order.total_price == 4990 + 500 + 1000
