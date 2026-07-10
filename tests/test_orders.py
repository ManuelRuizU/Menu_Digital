import json
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from app.models import BUSINESS_TZ, BundlePromo, Category, Coupon, Courier, Order, OrderItem, Product, User
from app.utils import day_range_utc


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _create_product(db, stock_quantity=None, price=1000, name='Bebida'):
    category = Category(name='Bebidas')
    db.session.add(category)
    db.session.commit()
    product = Product(name=name, description='Test', price=price,
                       category_id=category.id, stock_quantity=stock_quantity)
    db.session.add(product)
    db.session.commit()
    return product


def _create_order_with_item(db, product, quantity=1, shipping_cost=0, payment_method='efectivo',
                             delivery_mode='retira'):
    order = Order(customer_name='Cliente', phone='56911112222', delivery_mode=delivery_mode,
                  payment_method=payment_method, shipping_cost=shipping_cost,
                  total_price=product.price * quantity + shipping_cost, status='Pending')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=quantity, price=product.price))
    db.session.commit()
    return order


def _create_coupon(db, **overrides):
    defaults = dict(code='PRIMERACOMPRA', discount_percent=10, scope='order', is_active=True)
    defaults.update(overrides)
    coupon = Coupon(**defaults)
    db.session.add(coupon)
    db.session.commit()
    return coupon


def _create_promo(db, products, buy_quantity=2, pay_quantity=1, **overrides):
    promo = BundlePromo(label='Promo', buy_quantity=buy_quantity, pay_quantity=pay_quantity,
                         is_active=True, **overrides)
    db.session.add(promo)
    db.session.flush()
    promo.products = products
    db.session.commit()
    return promo


def _create_courier(db, name='Repartidor', whatsapp_number='56900000000'):
    courier = Courier(name=name, whatsapp_number=whatsapp_number)
    db.session.add(courier)
    db.session.commit()
    return courier


# --- stock decrement on public checkout (/api/orders) ---

def test_create_order_decrements_stock(client, db):
    product = _create_product(db, stock_quantity=5)

    resp = client.post('/api/orders', json={
        'items': [{'id': product.id, 'quantity': 2}],
        'customerName': 'Cliente', 'phone': '56911112222',
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True

    db.session.refresh(product)
    assert product.stock_quantity == 3
    assert product.sold_out is False


def test_create_order_marks_sold_out_at_zero_stock(client, db):
    product = _create_product(db, stock_quantity=2)

    resp = client.post('/api/orders', json={
        'items': [{'id': product.id, 'quantity': 2}],
        'customerName': 'Cliente', 'phone': '56911112222',
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    assert resp.status_code == 200

    db.session.refresh(product)
    assert product.stock_quantity == 0
    assert product.sold_out is True


def test_create_order_rejects_insufficient_stock(client, db):
    product = _create_product(db, stock_quantity=1)

    resp = client.post('/api/orders', json={
        'items': [{'id': product.id, 'quantity': 5}],
        'customerName': 'Cliente', 'phone': '56911112222',
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False

    db.session.refresh(product)
    assert product.stock_quantity == 1  # unchanged - the rejected order must not touch stock


def test_create_order_with_unlimited_stock_product(client, db):
    product = _create_product(db, stock_quantity=None)

    resp = client.post('/api/orders', json={
        'items': [{'id': product.id, 'quantity': 100}],
        'customerName': 'Cliente', 'phone': '56911112222',
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    assert resp.status_code == 200

    db.session.refresh(product)
    assert product.stock_quantity is None
    assert product.sold_out is False


# --- stock decrement/restore via the admin order-item editor ---

def test_add_order_item_decrements_stock(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=5)
    # _create_order_with_item inserts the order directly, bypassing checkout - so
    # stock still reflects only what add_order_item itself is about to decrement.
    order = _create_order_with_item(db, product, quantity=1)

    resp = client.post(f'/admin/orders/{order.id}/items/add', data={
        'product_id': product.id, 'quantity': 2,
    })
    assert resp.status_code == 302

    db.session.refresh(product)
    assert product.stock_quantity == 3  # 5 - 2 (added)


def test_remove_order_item_restores_stock(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=5)
    # Simulate stock already reduced by the initial item (as if it came through checkout).
    product.stock_quantity = 3
    order = _create_order_with_item(db, product, quantity=2)
    # A second item so removal is allowed (an order must keep at least one item).
    other_product = _create_product(db, stock_quantity=None, price=500)
    db.session.add(OrderItem(order_id=order.id, product_id=other_product.id, product_name=other_product.name,
                              quantity=1, price=500))
    db.session.commit()

    item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
    resp = client.post(f'/admin/orders/{order.id}/items/{item.id}/remove')
    assert resp.status_code == 302

    db.session.refresh(product)
    assert product.stock_quantity == 5  # 3 + 2 restored


def test_remove_order_item_clears_sold_out_when_restored(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=0)
    product.sold_out = True
    order = _create_order_with_item(db, product, quantity=2)
    other_product = _create_product(db, stock_quantity=None, price=500)
    db.session.add(OrderItem(order_id=order.id, product_id=other_product.id, product_name=other_product.name,
                              quantity=1, price=500))
    db.session.commit()

    item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
    client.post(f'/admin/orders/{order.id}/items/{item.id}/remove')

    db.session.refresh(product)
    assert product.stock_quantity == 2
    assert product.sold_out is False


# --- order total recalculation ---

def test_add_order_item_recalculates_total(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, stock_quantity=None)
    order = _create_order_with_item(db, product, quantity=1)  # total starts at 1000
    other = _create_product(db, price=500, stock_quantity=None)

    client.post(f'/admin/orders/{order.id}/items/add', data={'product_id': other.id, 'quantity': 3})

    db.session.refresh(order)
    assert order.total_price == 1000 + 500 * 3


def test_remove_order_item_recalculates_total(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, stock_quantity=None)
    other = _create_product(db, price=500, stock_quantity=None)
    order = _create_order_with_item(db, product, quantity=1)
    db.session.add(OrderItem(order_id=order.id, product_id=other.id, product_name=other.name,
                              quantity=2, price=500))
    order.total_price = 1000 + 500 * 2
    db.session.commit()

    item = OrderItem.query.filter_by(order_id=order.id, product_id=other.id).first()
    client.post(f'/admin/orders/{order.id}/items/{item.id}/remove')

    db.session.refresh(order)
    assert order.total_price == 1000


# --- order total recalculation: coupon + bundle promo re-evaluated after editing ---

def test_add_order_item_reapplies_percent_coupon_over_new_subtotal(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, stock_quantity=None)
    order = _create_order_with_item(db, product, quantity=1, shipping_cost=1500)
    coupon = _create_coupon(db, discount_percent=10, scope='order', applies_to_shipping=False)
    order.coupon_id = coupon.id
    db.session.commit()

    other = _create_product(db, price=500, stock_quantity=None)
    client.post(f'/admin/orders/{order.id}/items/add', data={'product_id': other.id, 'quantity': 1})

    db.session.refresh(order)
    # subtotal = 1000 + 500 = 1500; coupon = 10% of 1500 (shipping excluded) = 150
    assert order.discount_amount == 150
    assert order.bundle_discount_amount == 0
    assert order.total_price == 1500 + 1500 - 150  # subtotal + shipping - coupon


def test_bundle_promo_appears_and_disappears_as_items_are_edited(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, stock_quantity=None)
    _create_promo(db, [product], buy_quantity=2, pay_quantity=1)
    order = _create_order_with_item(db, product, quantity=1, shipping_cost=1500)

    # Adding a second unit of the same product (as a separate line, like the panel does)
    # completes the 2x1.
    client.post(f'/admin/orders/{order.id}/items/add', data={'product_id': product.id, 'quantity': 1})

    db.session.refresh(order)
    assert order.bundle_discount_amount == 1000  # 1 free unit at $1000
    assert order.total_price == 2000 + 1500 - 1000  # subtotal(2000) + shipping - bundle

    # Removing one of the two lines breaks the 2x1 again.
    second_item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id) \
        .order_by(OrderItem.id.desc()).first()
    client.post(f'/admin/orders/{order.id}/items/{second_item.id}/remove')

    db.session.refresh(order)
    assert order.bundle_discount_amount == 0
    assert order.total_price == 1000 + 1500  # subtotal(1 unit) + shipping, no promo


def test_removing_last_applicable_product_zeroes_products_scope_coupon_without_error(client, db):
    _register_owner(client)
    target = _create_product(db, price=1000, name='Target', stock_quantity=None)
    other = _create_product(db, price=500, name='Other', stock_quantity=None)
    coupon = _create_coupon(db, discount_percent=20, scope='products')
    coupon.products = [target]
    db.session.commit()

    order = _create_order_with_item(db, target, quantity=1, shipping_cost=1500)
    db.session.add(OrderItem(order_id=order.id, product_id=other.id, product_name=other.name,
                              quantity=1, price=other.price))
    order.coupon_id = coupon.id
    db.session.commit()

    target_item = OrderItem.query.filter_by(order_id=order.id, product_id=target.id).first()
    resp = client.post(f'/admin/orders/{order.id}/items/{target_item.id}/remove')

    assert resp.status_code == 302  # edit succeeds, no error raised/blocked
    db.session.refresh(order)
    assert order.discount_amount == 0
    assert order.total_price == 500 + 1500  # only "other" left + shipping, no discount


def test_orphan_item_excluded_from_bundle_promo_without_crashing(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, name='Bundled', stock_quantity=None)
    _create_promo(db, [product], buy_quantity=2, pay_quantity=1)
    order = _create_order_with_item(db, product, quantity=1, shipping_cost=1500)
    # Orphan line: product deleted after the sale, only the price/name snapshot remains.
    db.session.add(OrderItem(order_id=order.id, product_id=None, product_name='Producto eliminado',
                              quantity=1, price=800))
    db.session.commit()

    # Completing the 2x1 must not raise AttributeError from the orphan's product_id lookup.
    resp = client.post(f'/admin/orders/{order.id}/items/add', data={'product_id': product.id, 'quantity': 1})

    assert resp.status_code == 302
    db.session.refresh(order)
    assert order.bundle_discount_amount == 1000  # 1 free unit of the bundled product only
    # subtotal = 800 (orphan) + 1000*2 (bundled) = 2800
    assert order.total_price == 2800 + 1500 - 1000


def test_order_scope_coupon_shipping_discount_follows_applies_to_shipping_flag(client, db):
    _register_owner(client)

    # Flag off: shipping stays out of the discount base after the edit.
    product_a = _create_product(db, price=1000, name='A', stock_quantity=None)
    order_no_flag = _create_order_with_item(db, product_a, quantity=1, shipping_cost=1500)
    coupon_no_flag = _create_coupon(db, code='SINFLAG', discount_percent=10, scope='order',
                                     applies_to_shipping=False)
    order_no_flag.coupon_id = coupon_no_flag.id
    db.session.commit()
    other_a = _create_product(db, price=500, name='A2', stock_quantity=None)
    client.post(f'/admin/orders/{order_no_flag.id}/items/add', data={'product_id': other_a.id, 'quantity': 1})
    db.session.refresh(order_no_flag)
    assert order_no_flag.discount_amount == 150  # 10% of subtotal (1500) only

    # Flag on: shipping enters the discount base after the edit.
    product_b = _create_product(db, price=1000, name='B', stock_quantity=None)
    order_with_flag = _create_order_with_item(db, product_b, quantity=1, shipping_cost=1500)
    coupon_with_flag = _create_coupon(db, code='CONFLAG', discount_percent=10, scope='order',
                                       applies_to_shipping=True)
    order_with_flag.coupon_id = coupon_with_flag.id
    db.session.commit()
    other_b = _create_product(db, price=500, name='B2', stock_quantity=None)
    client.post(f'/admin/orders/{order_with_flag.id}/items/add', data={'product_id': other_b.id, 'quantity': 1})
    db.session.refresh(order_with_flag)
    assert order_with_flag.discount_amount == 300  # 10% of subtotal(1500) + shipping(1500) = 3000


def test_total_clamps_to_zero_when_discount_exceeds_subtotal_and_shipping(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, stock_quantity=None)
    order = _create_order_with_item(db, product, quantity=1, shipping_cost=1500)
    coupon = _create_coupon(db, discount_percent=150, scope='order', applies_to_shipping=True)
    order.coupon_id = coupon.id
    db.session.commit()

    client.post(f'/admin/orders/{order.id}/items/add', data={'product_id': product.id, 'quantity': 1})

    db.session.refresh(order)
    # subtotal(2000) + shipping(1500) = 3500 applicable; 150% of that is 5250 - far over the total
    assert order.total_price == 0


# --- explicit order status transitions (A2.1): confirm/cancel replace the old toggle ---

def test_confirm_order_moves_pending_to_confirmed(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))  # starts Pending
    before = datetime.utcnow()
    today_santiago = datetime.now(BUSINESS_TZ).date()

    resp = client.post(f'/admin/orders/{order.id}/confirm')

    assert resp.status_code == 302
    db.session.refresh(order)
    assert order.status == 'Confirmed'
    assert order.confirmed_at is not None
    assert before <= order.confirmed_at <= datetime.utcnow()
    assert order.confirmed_date == today_santiago
    assert order.daily_number == 1  # first order confirmed today, in a fresh test db


def test_confirm_order_on_already_confirmed_is_a_noop(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))
    order.status = 'Confirmed'
    first_confirmed_at = datetime(2026, 1, 1, 12, 0, 0)
    order.confirmed_at = first_confirmed_at
    order.confirmed_date = first_confirmed_at.date()
    order.daily_number = 1
    db.session.commit()

    resp = client.post(f'/admin/orders/{order.id}/confirm')

    assert resp.status_code == 302  # no 500, just redirected with a flash
    db.session.refresh(order)
    assert order.status == 'Confirmed'
    assert order.confirmed_at == first_confirmed_at  # the no-op must not touch it
    assert order.confirmed_date == first_confirmed_at.date()
    assert order.daily_number == 1  # not reassigned, not bumped


def test_confirm_order_on_cancelled_is_a_noop(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))
    order.status = 'Cancelled'
    db.session.commit()

    resp = client.post(f'/admin/orders/{order.id}/confirm')

    assert resp.status_code == 302
    db.session.refresh(order)
    assert order.status == 'Cancelled'  # a cancelled order can never become Confirmed
    assert order.confirmed_at is None  # it was never actually confirmed
    assert order.confirmed_date is None
    assert order.daily_number is None


# --- daily_number (A2.4): per-day correlative assigned once, on first confirmation ---

def test_daily_number_increments_in_confirmation_order_same_day(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    order_a = _create_order_with_item(db, product)
    order_b = _create_order_with_item(db, product)

    client.post(f'/admin/orders/{order_a.id}/confirm')
    client.post(f'/admin/orders/{order_b.id}/confirm')

    db.session.refresh(order_a)
    db.session.refresh(order_b)
    assert order_a.daily_number == 1
    assert order_b.daily_number == 2


def test_daily_number_of_cancelled_order_is_not_reused(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    order_a = _create_order_with_item(db, product)
    order_b = _create_order_with_item(db, product)
    order_c = _create_order_with_item(db, product)

    client.post(f'/admin/orders/{order_a.id}/confirm')  # daily_number 1
    client.post(f'/admin/orders/{order_b.id}/confirm')  # daily_number 2
    client.post(f'/admin/orders/{order_b.id}/cancel')   # keeps daily_number 2, per design
    client.post(f'/admin/orders/{order_c.id}/confirm')  # must be 3, not 2 again (MAX+1, not COUNT+1)

    db.session.refresh(order_a)
    db.session.refresh(order_b)
    db.session.refresh(order_c)
    assert order_a.daily_number == 1
    assert order_b.daily_number == 2  # cancelled, but keeps its number
    assert order_b.status == 'Cancelled'
    assert order_c.daily_number == 3  # NOT 2 - a COUNT-based scheme would have reused it


def test_daily_number_resets_on_a_new_day(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)

    # Order confirmed "yesterday" (Santiago time) - simulated the same way A2.2/A2.3
    # tests anchor a day boundary: set confirmed_at/confirmed_date directly rather
    # than going through confirm_order(), since we can't travel back in time.
    order_yesterday = _create_order_with_item(db, product)
    order_yesterday.status = 'Confirmed'
    yesterday_start_utc, _ = day_range_utc(datetime.now(BUSINESS_TZ).date() - timedelta(days=1))
    order_yesterday.confirmed_at = yesterday_start_utc + timedelta(hours=12)
    order_yesterday.confirmed_date = (yesterday_start_utc + timedelta(hours=12)).date()
    order_yesterday.daily_number = 1
    db.session.commit()

    order_today = _create_order_with_item(db, product)
    client.post(f'/admin/orders/{order_today.id}/confirm')

    db.session.refresh(order_today)
    assert order_today.daily_number == 1  # today's count starts over, ignores yesterday's MAX


def test_confirmed_date_daily_number_unique_constraint_is_enforced_by_the_db(db):
    """Direct proof that UNIQUE(confirmed_date, daily_number) actually exists and is
    enforced by the database engine itself - independent of confirm_order()'s retry
    logic (tested elsewhere with a MOCKED IntegrityError, not a real constraint hit).
    If a future migration ever dropped this constraint by mistake, the two collision
    tests below would stay green regardless (their exception is injected, not real) -
    this is the one test that would actually catch that regression."""
    from sqlalchemy.exc import IntegrityError

    product = _create_product(db, stock_quantity=None)
    same_date = datetime.now(BUSINESS_TZ).date()

    order_a = _create_order_with_item(db, product)
    order_a.status = 'Confirmed'
    order_a.confirmed_date = same_date
    order_a.daily_number = 1
    db.session.commit()

    order_b = _create_order_with_item(db, product)
    order_b.status = 'Confirmed'
    order_b.confirmed_date = same_date
    order_b.daily_number = 1  # same (confirmed_date, daily_number) pair as order_a

    with pytest.raises(IntegrityError):
        db.session.commit()

    db.session.rollback()
    db.session.refresh(order_a)
    assert order_a.daily_number == 1  # order_a's row is untouched by order_b's failed insert


def test_daily_number_collision_retries_with_a_fresh_max(client, db, monkeypatch):
    """Simulates a race with another worker: the first commit attempt raises
    IntegrityError (as the real UNIQUE(confirmed_date, daily_number) constraint
    would on a genuine collision), and confirm_order must recover by rolling back
    and retrying with a fresh MAX instead of 500ing or leaving the order half-set."""
    from sqlalchemy.exc import IntegrityError
    from app.catalog import routes as catalog_routes

    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    order = _create_order_with_item(db, product)

    real_commit = catalog_routes.db.session.commit
    call_count = {'n': 0}

    def flaky_commit():
        call_count['n'] += 1
        if call_count['n'] == 1:
            raise IntegrityError('mock unique violation', {}, Exception('UNIQUE constraint failed'))
        return real_commit()

    monkeypatch.setattr(catalog_routes.db.session, 'commit', flaky_commit)

    resp = client.post(f'/admin/orders/{order.id}/confirm')

    assert resp.status_code == 302
    assert call_count['n'] == 2  # failed once, succeeded on the retry
    db.session.refresh(order)
    assert order.status == 'Confirmed'
    assert order.daily_number == 1  # the retry still landed on the correct number


def test_daily_number_collision_gives_up_after_max_attempts_without_corrupting_data(client, db, monkeypatch):
    """If every retry keeps colliding (pathological case), confirm_order must not
    loop forever and must not fall back to assigning a duplicate - better a visible,
    honest error than silently corrupting the daily_number sequence."""
    from sqlalchemy.exc import IntegrityError
    from app.catalog import routes as catalog_routes

    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    order = _create_order_with_item(db, product)

    call_count = {'n': 0}

    def always_flaky_commit():
        call_count['n'] += 1
        raise IntegrityError('mock unique violation', {}, Exception('UNIQUE constraint failed'))

    monkeypatch.setattr(catalog_routes.db.session, 'commit', always_flaky_commit)

    resp = client.post(f'/admin/orders/{order.id}/confirm')

    assert resp.status_code == 302  # a flash + redirect, not a 500
    assert call_count['n'] == catalog_routes.CONFIRM_ORDER_MAX_ATTEMPTS  # capped, not an infinite loop
    db.session.refresh(order)
    # Since every commit failed, nothing was actually persisted - the order is
    # exactly as it was before the attempt, not half-confirmed with no number.
    assert order.status == 'Pending'
    assert order.daily_number is None


def test_cancel_order_from_pending(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))

    resp = client.post(f'/admin/orders/{order.id}/cancel')

    assert resp.status_code == 302
    db.session.refresh(order)
    assert order.status == 'Cancelled'


def test_cancel_order_from_confirmed(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))
    order.status = 'Confirmed'
    db.session.commit()

    resp = client.post(f'/admin/orders/{order.id}/cancel')

    assert resp.status_code == 302
    db.session.refresh(order)
    assert order.status == 'Cancelled'


def test_cancel_order_on_already_cancelled_is_a_noop(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))
    order.status = 'Cancelled'
    db.session.commit()

    resp = client.post(f'/admin/orders/{order.id}/cancel')

    assert resp.status_code == 302  # no 500
    db.session.refresh(order)
    assert order.status == 'Cancelled'


def test_old_toggle_status_route_no_longer_exists(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))
    order.status = 'Confirmed'
    db.session.commit()

    resp = client.post(f'/admin/orders/{order.id}/toggle-status')

    assert resp.status_code == 404
    db.session.refresh(order)
    assert order.status == 'Confirmed'  # nothing could have reverted it - the route is gone


# --- payment status (A2.2): second, independent axis from sale status ---

def test_new_order_starts_with_pending_payment_status(client, db):
    product = _create_product(db, stock_quantity=None)

    resp = client.post('/api/orders', json={
        'items': [{'id': product.id, 'quantity': 1}],
        'customerName': 'Cliente', 'phone': '56911112222',
        'deliveryMode': 'retira', 'paymentMethod': 'transferencia',
    })
    assert resp.status_code == 200

    order = Order.query.order_by(Order.id.desc()).first()
    # Even for transferencia (which becomes 'paid' automatically on confirm), a
    # freshly created, unconfirmed order always starts 'pending' - the auto-mark
    # only happens inside confirm_order(), not at checkout.
    assert order.status == 'Pending'
    assert order.payment_status == 'pending'


def test_confirming_transfer_order_marks_it_paid_automatically(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None),
                                     payment_method='transferencia')

    client.post(f'/admin/orders/{order.id}/confirm')

    db.session.refresh(order)
    assert order.status == 'Confirmed'
    assert order.payment_status == 'paid'


def test_confirming_cash_order_leaves_payment_pending(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None),
                                     payment_method='efectivo')

    client.post(f'/admin/orders/{order.id}/confirm')

    db.session.refresh(order)
    assert order.status == 'Confirmed'
    assert order.payment_status == 'pending'  # cash is collected on delivery, not now


def test_confirming_card_order_leaves_payment_pending(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None),
                                     payment_method='tarjeta')

    client.post(f'/admin/orders/{order.id}/confirm')

    db.session.refresh(order)
    assert order.status == 'Confirmed'
    assert order.payment_status == 'pending'  # "tarjeta al recibir" - courier brings the card machine


def test_mark_order_paid_moves_pending_to_paid(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None),
                                     payment_method='efectivo')

    resp = client.post(f'/admin/orders/{order.id}/mark-paid')

    assert resp.status_code == 302
    db.session.refresh(order)
    assert order.payment_status == 'paid'


def test_mark_order_unpaid_moves_paid_to_pending(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None),
                                     payment_method='transferencia')
    order.payment_status = 'paid'
    db.session.commit()

    resp = client.post(f'/admin/orders/{order.id}/mark-unpaid')

    assert resp.status_code == 302
    db.session.refresh(order)
    assert order.payment_status == 'pending'


def test_dashboard_confirmed_unpaid_count_excludes_cancelled_and_pending_sale(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    today_start_utc, _ = day_range_utc(datetime.now(BUSINESS_TZ).date())

    # Confirmed + unpaid + confirmed today: the one case that should be counted.
    counted = _create_order_with_item(db, product, payment_method='efectivo')
    counted.status = 'Confirmed'
    counted.confirmed_at = today_start_utc + timedelta(hours=1)
    # Confirmed + already paid: not counted (nothing owed).
    confirmed_paid = _create_order_with_item(db, product, payment_method='transferencia')
    confirmed_paid.status = 'Confirmed'
    confirmed_paid.payment_status = 'paid'
    confirmed_paid.confirmed_at = today_start_utc + timedelta(hours=1)
    # Cancelled + unpaid: not counted (sale didn't happen, nothing to collect).
    cancelled_unpaid = _create_order_with_item(db, product, payment_method='efectivo')
    cancelled_unpaid.status = 'Cancelled'
    # Pending sale + unpaid: not counted (not confirmed as a real sale yet, confirmed_at is None).
    pending_sale = _create_order_with_item(db, product, payment_method='efectivo')
    # Confirmed + unpaid, but CONFIRMED YESTERDAY: not counted - the figure is scoped
    # to today's close-of-day, not lifetime debt. created_at is deliberately today to
    # prove the filter anchors on confirmed_at, not created_at.
    confirmed_yesterday = _create_order_with_item(db, product, payment_method='efectivo')
    confirmed_yesterday.status = 'Confirmed'
    yesterday_start_utc, _ = day_range_utc(datetime.now(BUSINESS_TZ).date() - timedelta(days=1))
    confirmed_yesterday.confirmed_at = yesterday_start_utc + timedelta(hours=12)
    # Confirmed + unpaid, but confirmed_at is NULL: legacy row from before A2.3 (or a
    # data bug) - must not count, since we can't tell it happened today. This is the
    # exact shape the migration backfill leaves pre-existing Confirmed orders in.
    legacy_confirmed_no_timestamp = _create_order_with_item(db, product, payment_method='efectivo')
    legacy_confirmed_no_timestamp.status = 'Confirmed'
    db.session.commit()

    resp = client.get('/admin/dashboard')
    html = resp.data.decode()

    assert resp.status_code == 200
    # Pull the number straight out of the rendered card, right after its label - the
    # expected value (1) is hand-counted above, not re-derived from the route's own filter.
    match = re.search(r'Confirmados sin pagar</div>\s*<div[^>]*>(\d+)</div>', html)
    assert match is not None
    assert match.group(1) == '1'


# --- send_route (A2.4 part 3, option B): batch dispatch, confirmed-only ---

def _message_from_redirect(resp):
    location = resp.headers['Location']
    query = parse_qs(urlparse(location).query)
    return location, query.get('text', [''])[0]


def test_send_route_all_confirmed_with_courier(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    order_a = _create_order_with_item(db, product, delivery_mode='envio')
    order_a.customer_name = 'Ana'
    order_b = _create_order_with_item(db, product, delivery_mode='envio')
    order_b.customer_name = 'Beto'
    db.session.commit()
    client.post(f'/admin/orders/{order_a.id}/confirm')
    client.post(f'/admin/orders/{order_b.id}/confirm')
    courier = _create_courier(db)

    resp = client.post('/admin/orders/send-route', data={
        'order_ids': [order_a.id, order_b.id],
        'courier_id': courier.id,
    })

    assert resp.status_code == 302
    location, message = _message_from_redirect(resp)
    assert location.startswith(f'https://wa.me/{courier.whatsapp_number}')
    assert 'Ana' in message
    assert 'Beto' in message


def test_send_route_all_confirmed_without_courier_uses_modo_libre(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    order_a = _create_order_with_item(db, product, delivery_mode='envio')
    order_a.customer_name = 'Ana'
    order_b = _create_order_with_item(db, product, delivery_mode='envio')
    order_b.customer_name = 'Beto'
    db.session.commit()
    client.post(f'/admin/orders/{order_a.id}/confirm')
    client.post(f'/admin/orders/{order_b.id}/confirm')

    resp = client.post('/admin/orders/send-route', data={
        'order_ids': [order_a.id, order_b.id],
    })

    assert resp.status_code == 302
    location, message = _message_from_redirect(resp)
    assert location.startswith('https://wa.me/?text=')  # modo libre - no courier number
    assert 'Ana' in message
    assert 'Beto' in message


def test_send_route_mixed_batch_builds_route_with_confirmed_only(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    order_a = _create_order_with_item(db, product, delivery_mode='envio')
    order_a.customer_name = 'Ana'
    order_b = _create_order_with_item(db, product, delivery_mode='envio')
    order_b.customer_name = 'Beto'
    order_pending = _create_order_with_item(db, product, delivery_mode='envio')
    order_pending.customer_name = 'Cancelado O Pendiente'
    db.session.commit()
    client.post(f'/admin/orders/{order_a.id}/confirm')
    client.post(f'/admin/orders/{order_b.id}/confirm')
    # order_pending stays Pending - never confirmed.

    resp = client.post('/admin/orders/send-route', data={
        'order_ids': [order_a.id, order_b.id, order_pending.id],
    })

    # Success path: at least one confirmed order means the route still gets built and
    # redirects straight to wa.me (not back to catalog.orders).
    assert resp.status_code == 302
    location, message = _message_from_redirect(resp)
    assert location.startswith('https://wa.me/')
    assert 'Ana' in message
    assert 'Beto' in message
    assert 'Cancelado O Pendiente' not in message  # the unconfirmed one never made it in

    # The "quedaron afuera" flash can't be read by following the redirect - it points
    # to an external URL (wa.me), so no further request of ours ever renders it via
    # get_flashed_messages(). Instead, inspect the session cookie directly (the
    # standard Flask test idiom for checking flashes without a page render).
    with client.session_transaction() as sess:
        flashed = [message_text for _category, message_text in sess.get('_flashes', [])]
    assert any('Quedaron afuera por no estar confirmados' in text and 'Cancelado O Pendiente' in text
               for text in flashed)


def test_send_route_all_unconfirmed_blocks_and_redirects_to_orders(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    order_a = _create_order_with_item(db, product, delivery_mode='envio')
    order_b = _create_order_with_item(db, product, delivery_mode='envio')
    # Neither gets confirmed.

    resp = client.post('/admin/orders/send-route', data={
        'order_ids': [order_a.id, order_b.id],
    }, follow_redirects=True)

    assert resp.status_code == 200  # followed the redirect back into our own app
    assert b'Ninguno de los pedidos marcados est\xc3\xa1 confirmado' in resp.data


def test_send_route_with_no_orders_marked(client, db):
    _register_owner(client)

    resp = client.post('/admin/orders/send-route', data={}, follow_redirects=True)

    assert resp.status_code == 200
    assert 'Marca al menos un pedido'.encode() in resp.data


def test_send_route_orders_by_requested_time_not_by_order_ids_order(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    order_late = _create_order_with_item(db, product, delivery_mode='envio')
    order_late.customer_name = 'Later'
    order_late.requested_time = '20:00'
    order_early = _create_order_with_item(db, product, delivery_mode='envio')
    order_early.customer_name = 'Earlier'
    order_early.requested_time = '19:00'
    db.session.commit()
    # Confirm/mark them in reverse chronological order, on purpose.
    client.post(f'/admin/orders/{order_late.id}/confirm')
    client.post(f'/admin/orders/{order_early.id}/confirm')

    resp = client.post('/admin/orders/send-route', data={
        # order_ids also lists the late one first - the route order must not follow this.
        'order_ids': [order_late.id, order_early.id],
    })

    assert resp.status_code == 302
    _location, message = _message_from_redirect(resp)
    assert message.index('Earlier') < message.index('Later')  # 19:00 stop comes before 20:00
