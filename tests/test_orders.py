import json
import re
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import event

from app.catalog.routes import _build_courier_message, _print_order_ticket, cash_payment_summary
from app.extensions import db as _db
from app.main import routes as main_routes
from app.models import (BUSINESS_TZ, BundlePromo, BusinessHours, Category, Coupon, Courier, Order, OrderItem,
                         OrderItemOption, Product, ProductOption, ProductOptionGroup, Subcategory, User)
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

def test_create_order_decrements_stock(client, db, order_payload):
    product = _create_product(db, stock_quantity=5)

    resp = client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 2}]))
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True

    db.session.refresh(product)
    assert product.stock_quantity == 3
    assert product.sold_out is False


def test_create_order_marks_sold_out_at_zero_stock(client, db, order_payload):
    product = _create_product(db, stock_quantity=2)

    resp = client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 2}]))
    assert resp.status_code == 200

    db.session.refresh(product)
    assert product.stock_quantity == 0
    assert product.sold_out is True


def test_create_order_rejects_insufficient_stock(client, db, order_payload):
    product = _create_product(db, stock_quantity=1)

    resp = client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 5}]))
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False

    db.session.refresh(product)
    assert product.stock_quantity == 1  # unchanged - the rejected order must not touch stock


def test_create_order_with_unlimited_stock_product(client, db, order_payload):
    product = _create_product(db, stock_quantity=None)

    resp = client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 100}]))
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

def test_new_order_starts_with_pending_payment_status(client, db, order_payload):
    product = _create_product(db, stock_quantity=None)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], paymentMethod='transferencia'))
    assert resp.status_code == 200

    order = Order.query.order_by(Order.id.desc()).first()
    # A freshly created, unconfirmed order always starts 'pending', regardless of
    # payment_method - nothing auto-marks payment_status, ever (A2.2.1: every
    # payment is confirmed manually by the owner, no method is an exception).
    assert order.status == 'Pending'
    assert order.payment_status == 'pending'


def test_confirming_transfer_order_leaves_payment_pending(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None),
                                     payment_method='transferencia')

    client.post(f'/admin/orders/{order.id}/confirm')

    db.session.refresh(order)
    assert order.status == 'Confirmed'
    # A2.2.1: transferencia is no longer auto-marked 'paid' on confirm - some
    # customers transfer right away, others take a while, so the owner marks it
    # manually once they actually see the money (WhatsApp receipt, bank app, etc).
    assert order.payment_status == 'pending'


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


# --- required fields on checkout (Paso 1): horario obligatorio, direccion opcional en retiro ---

def test_create_order_without_requested_time_fails(client, db, order_payload):
    product = _create_product(db, stock_quantity=None)
    payload = order_payload(items=[{'id': product.id, 'quantity': 1}])
    del payload['requestedTime']

    resp = client.post('/api/orders', json=payload)

    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False
    assert Order.query.count() == 0


def test_create_order_without_customer_name_fails(client, db, order_payload):
    product = _create_product(db, stock_quantity=None)
    payload = order_payload(items=[{'id': product.id, 'quantity': 1}])
    del payload['customerName']

    resp = client.post('/api/orders', json=payload)

    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False
    assert Order.query.count() == 0


def test_create_order_without_phone_fails(client, db, order_payload):
    product = _create_product(db, stock_quantity=None)
    payload = order_payload(items=[{'id': product.id, 'quantity': 1}])
    del payload['phone']

    resp = client.post('/api/orders', json=payload)

    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False
    assert Order.query.count() == 0


def test_create_order_despacho_without_address_fails(client, db, order_payload):
    product = _create_product(db, stock_quantity=None)
    payload = order_payload(items=[{'id': product.id, 'quantity': 1}],
                             deliveryMode='envio', lat=-33.5, lng=-70.5)
    # deliberately no 'address' - despacho requires it, unlike retiro

    resp = client.post('/api/orders', json=payload)

    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False
    assert Order.query.count() == 0


def test_create_order_retiro_without_address_succeeds(client, db, order_payload):
    product = _create_product(db, stock_quantity=None)

    resp = client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 1}]))

    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    order = Order.query.order_by(Order.id.desc()).first()
    assert order.address is None  # retiro never required one


def test_create_order_with_all_required_fields_saves_requested_time(client, db, order_payload):
    product = _create_product(db, stock_quantity=None)

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], requestedTime='20:30'))

    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    order = Order.query.order_by(Order.id.desc()).first()
    assert order.requested_time == '20:30'


# --- orders() view grouping/sort: Pending on top (oldest-waiting first), then
# Confirmed (by requested_time), then Cancelled last - so the encargado never has
# to hunt through the list for what still needs a decision ---

def test_orders_view_lists_pending_before_confirmed_even_with_earlier_requested_time(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    confirmed = _create_order_with_item(db, product)
    confirmed.customer_name = 'Confirmado13'
    confirmed.requested_time = '13:00'
    confirmed.status = 'Confirmed'
    pending = _create_order_with_item(db, product)
    pending.customer_name = 'Pendiente20'
    pending.requested_time = '20:00'
    db.session.commit()

    resp = client.get('/admin/orders')

    assert resp.status_code == 200
    html = resp.data.decode()
    # Pending must appear first even though its delivery time (20:00) is later than
    # the confirmed order's (13:00) - status takes priority over requested_time.
    assert html.index('Pendiente20') < html.index('Confirmado13')


def test_orders_view_pending_orders_sorted_oldest_first(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    today_start_utc, _ = day_range_utc(datetime.now(BUSINESS_TZ).date())
    newer = _create_order_with_item(db, product)
    newer.customer_name = 'Nuevo'
    newer.created_at = today_start_utc + timedelta(hours=10)
    older = _create_order_with_item(db, product)
    older.customer_name = 'Viejo'
    older.created_at = today_start_utc + timedelta(hours=8)
    db.session.commit()

    resp = client.get('/admin/orders')

    assert resp.status_code == 200
    html = resp.data.decode()
    # The order waiting longest (oldest created_at) is the most urgent - it goes first.
    assert html.index('Viejo') < html.index('Nuevo')


def test_orders_view_cancelled_orders_go_last(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    cancelled = _create_order_with_item(db, product)
    cancelled.customer_name = 'Cancelado'
    cancelled.status = 'Cancelled'
    confirmed = _create_order_with_item(db, product)
    confirmed.customer_name = 'Confirmado'
    confirmed.status = 'Confirmed'
    pending = _create_order_with_item(db, product)
    pending.customer_name = 'Pendiente'
    db.session.commit()

    resp = client.get('/admin/orders')

    assert resp.status_code == 200
    html = resp.data.decode()
    assert html.index('Pendiente') < html.index('Confirmado') < html.index('Cancelado')


def test_orders_view_shows_all_three_statuses_and_their_group_headers(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    pending = _create_order_with_item(db, product)
    pending.customer_name = 'UnoPendiente'
    confirmed = _create_order_with_item(db, product)
    confirmed.customer_name = 'DosConfirmado'
    confirmed.status = 'Confirmed'
    cancelled = _create_order_with_item(db, product)
    cancelled.customer_name = 'TresCancelado'
    cancelled.status = 'Cancelled'
    db.session.commit()

    resp = client.get('/admin/orders')

    assert resp.status_code == 200
    html = resp.data.decode()
    # Reordering must not filter anything out - all 3 statuses still render.
    assert 'UnoPendiente' in html
    assert 'DosConfirmado' in html
    assert 'TresCancelado' in html
    assert 'Por confirmar (1)' in html
    assert 'Confirmados (1)' in html
    assert 'Cancelados (1)' in html


# --- orders() view as an accordion: level 1 (summary) scannable, level 2 (detail) full ---

def test_orders_view_level1_summary_shows_scannable_fields_and_starts_collapsed(client, db):
    _register_owner(client)
    product = _create_product(db, price=5990, name='California Roll')
    order = _create_order_with_item(db, product, delivery_mode='retira')
    order.daily_number = 3
    order.requested_time = '19:30'
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert f'<details class="order-card" id="order-{order.id}">' in html  # collapsed - no "open" attribute
    assert '#3' in html
    assert '19:30' in html
    assert 'Retiro' in html
    assert '$5990' in html
    assert 'agenda-payment-pill unpaid' in html  # payment status pill, color+shape pattern reused from Agenda
    assert '⚠ Sin pagar' in html


def test_orders_view_detail_shows_phone_as_text_full_breakdown_coupon_and_change(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, name='Producto')
    coupon = _create_coupon(db, code='PROMO10', discount_percent=10, scope='order')
    order = Order(customer_name='Cliente Test', phone='56911112222', delivery_mode='envio',
                  address='Sevilla 632', payment_method='efectivo', shipping_cost=1500,
                  cash_amount=10000, coupon_id=coupon.id, discount_amount=250,
                  bundle_discount_amount=0, total_price=1000 + 1500 - 250, status='Pending')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=1000))
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    # Phone as readable text (not just buried in a wa.me href) and tappable via tel:.
    assert '56911112222' in html
    assert 'href="tel:56911112222"' in html
    # Full Subtotal/Envío/Descuento breakdown, not just the final Total.
    assert 'Subtotal: $1000' in html
    assert 'Envío: $1500' in html
    assert 'Descuento (PROMO10): -$250' in html
    # Cash change, reusing the same formula _build_courier_message already uses.
    change = order.cash_amount - order.total_price
    assert f'Paga con $10000 · vuelto ${change}' in html


def test_orders_view_bundle_discount_shown_in_breakdown_when_present(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, name='Producto')
    order = _create_order_with_item(db, product, shipping_cost=0)
    order.bundle_discount_amount = 300
    order.total_price = 1000 - 300
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert '2x1/3x2 aplicado: -$300' in html


def test_orders_view_marks_gift_item_explicitly_not_as_a_plain_zero_dollar_item(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, name='Plato Principal')
    gift_product = _create_product(db, price=2000, name='Postre de Regalo')
    owner = User.query.filter_by(is_owner=True).first()
    owner.gift_product_id = gift_product.id
    db.session.commit()

    order = _create_order_with_item(db, product)
    db.session.add(OrderItem(order_id=order.id, product_id=gift_product.id,
                              product_name=gift_product.name, quantity=1, price=0))
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'gift-badge' in html
    assert '🎁 Regalo' in html
    # Must not render as an unexplained $0 line item.
    assert '1× Postre de Regalo — $0' not in html


# --- orders() view: contextual actions appear only when their condition holds ---

def test_orders_view_retiro_order_has_no_courier_dispatch_action(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = _create_order_with_item(db, product, delivery_mode='retira')
    order.status = 'Confirmed'
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'Enviar a repartidor' not in html
    assert 'Incluir en el recorrido' not in html


def test_orders_view_paid_order_shows_only_mark_unpaid(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = _create_order_with_item(db, product)
    order.payment_status = 'paid'
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert '>Marcar no pagado<' in html
    assert '>Marcar pagado<' not in html


def test_orders_view_confirmed_order_has_no_confirm_button_but_keeps_cancel(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = _create_order_with_item(db, product)
    order.status = 'Confirmed'
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert '>Confirmar pedido<' not in html
    assert '>Cancelar pedido<' in html


def test_orders_view_cancelled_order_has_neither_confirm_nor_cancel_button(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = _create_order_with_item(db, product)
    order.status = 'Cancelled'
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert '>Confirmar pedido<' not in html
    assert '>Cancelar pedido<' not in html


# --- 3-level action hierarchy: exactly one primary action per order, or none ---

def test_orders_view_pending_order_shows_confirm_as_primary_action(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_order_with_item(db, product)  # starts Pending

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'class="order-action-primary"' in html
    assert 'Confirmar pedido' in html


def test_orders_view_confirmed_unpaid_order_shows_mark_paid_as_primary_action(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = _create_order_with_item(db, product)
    order.status = 'Confirmed'
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'class="order-action-primary"' in html
    assert '<button type="submit">Marcar pagado</button>' in html
    # Promoted to primary, not duplicated as a plain action-btn too.
    assert html.count('Marcar pagado') == 1


def test_orders_view_confirmed_paid_order_has_no_primary_action(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = _create_order_with_item(db, product)
    order.status = 'Confirmed'
    order.payment_status = 'paid'
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'class="order-action-primary"' not in html


def test_orders_view_pending_unpaid_order_keeps_mark_paid_in_frequent_actions(client, db):
    # The clarified rule: "Marcar pagado" keeps the exact same visibility condition
    # as before (payment_status == 'pending', regardless of order.status) - venta y
    # pago son ejes independientes. It just isn't promoted to primary unless the
    # order is also Confirmed; here (Pending) it stays a normal action-btn instead.
    _register_owner(client)
    product = _create_product(db)
    _create_order_with_item(db, product)  # Pending, payment_status defaults 'pending'

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'Confirmar pedido' in html  # this is the primary here
    assert 'action-btn">Marcar pagado' in html  # still present, as a frequent action


def test_orders_view_cancel_lives_inside_more_actions_not_the_frequent_row(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_order_with_item(db, product)

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert html.index('order-actions-frequent') < html.index('order-actions-more')
    assert html.index('order-actions-more') < html.index('Cancelar pedido')


# --- accordion-state preservation across the POST-redirect every action does ---

def test_confirm_order_redirect_includes_order_anchor_when_provided(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))

    resp = client.post(f'/admin/orders/{order.id}/confirm', data={'anchor': f'order-{order.id}'})

    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(f'#order-{order.id}')


def test_confirm_order_redirect_ignores_malformed_anchor(client, db):
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))

    resp = client.post(f'/admin/orders/{order.id}/confirm',
                        data={'anchor': '"><script>alert(1)</script>'})

    assert resp.status_code == 302
    assert '#' not in resp.headers['Location']


def test_confirm_order_redirect_has_no_anchor_when_not_provided(client, db):
    # Agenda/order_history forms don't send an anchor field at all - must not 500 or
    # produce a stray "#" with nothing after it.
    _register_owner(client)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))

    resp = client.post(f'/admin/orders/{order.id}/confirm')

    assert resp.status_code == 302
    assert '#' not in resp.headers['Location']


# --- accept_orders_outside_hours toggle: create_order() server-side gate on the
# CURRENT moment, independent from the pre-existing check on the requested delivery time ---

def _offset_time_str(minutes_offset):
    """A 'HH:MM' string minutes_offset away from the real current Santiago time,
    wrapped cyclically through a 24h clock. Built this way (not a fixed literal like
    '14:00') so the test is robust no matter what time of day the suite actually runs -
    the same time-of-day fragility documented elsewhere in this file for the Agenda."""
    now = datetime.now(BUSINESS_TZ)
    total = (now.hour * 60 + now.minute + minutes_offset) % 1440
    return f'{total // 60:02d}:{total % 60:02d}'


def _set_business_hours_for_today(db, opens_at, closes_at):
    today_weekday = datetime.now(BUSINESS_TZ).weekday()
    db.session.add(BusinessHours(day_of_week=today_weekday, opens_at=opens_at, closes_at=closes_at))
    db.session.commit()


def _freeze_time_of_day(monkeypatch, hour, minute):
    """Pins app.main.routes' notion of "now" to a fixed HH:MM, keeping today's real
    date/weekday intact (so a BusinessHours row set for 'today' still matches) -
    avoids hardcoding a calendar date whose weekday could drift out of sync."""
    real_datetime = datetime

    class FixedNow(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)

    monkeypatch.setattr(main_routes, 'datetime', FixedNow)


def test_create_order_blocked_outside_hours_when_toggle_off(client, db, order_payload):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    # accept_orders_outside_hours defaults to False - left untouched.
    opens = _offset_time_str(180)
    closes = _offset_time_str(300)
    _set_business_hours_for_today(db, opens, closes)

    resp = client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 1}]))

    assert resp.status_code == 400
    data = resp.get_json()
    assert data['ok'] is False
    assert 'horario' in data['message'].lower()
    assert Order.query.count() == 0


def test_create_order_allowed_inside_hours_regardless_of_toggle(client, db, order_payload):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    opens = _offset_time_str(-60)
    closes = _offset_time_str(60)
    _set_business_hours_for_today(db, opens, closes)
    now = _offset_time_str(0)  # safely inside the window above, by construction

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], requestedTime=now))

    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True


def test_create_order_allowed_outside_hours_when_toggle_on(client, db, order_payload):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    owner = User.query.filter_by(is_owner=True).first()
    owner.accept_orders_outside_hours = True
    opens = _offset_time_str(180)
    closes = _offset_time_str(300)
    _set_business_hours_for_today(db, opens, closes)
    db.session.commit()

    # The requested delivery slot still has to fall INSIDE the window - the toggle
    # only lifts the "can't even submit right now" gate, not the delivery-time check.
    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], requestedTime=opens))

    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True


def test_create_order_toggle_on_still_rejects_a_requested_time_outside_hours(client, db, order_payload):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    owner = User.query.filter_by(is_owner=True).first()
    owner.accept_orders_outside_hours = True
    opens = _offset_time_str(180)
    closes = _offset_time_str(300)
    _set_business_hours_for_today(db, opens, closes)
    db.session.commit()

    # Submitting right now (outside the window) is fine with the toggle ON, but asking
    # for a delivery slot that's ALSO outside the window must still fail - a separate,
    # pre-existing check the toggle was never meant to touch.
    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], requestedTime=_offset_time_str(0)))

    assert resp.status_code == 400
    assert Order.query.count() == 0


def test_create_order_closed_day_rejects_regardless_of_toggle(client, db, order_payload):
    # is_closed (opens_at/closes_at both None) is handled by an earlier, separate
    # check - the new guard must not weaken or duplicate it.
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    owner = User.query.filter_by(is_owner=True).first()
    owner.accept_orders_outside_hours = True
    # A day with real hours elsewhere in the week, so "nothing configured at all"
    # (which resolve_hours_for_day treats as unrestricted) doesn't mask today's
    # explicit is_closed row.
    other_day = (datetime.now(BUSINESS_TZ).weekday() + 1) % 7
    db.session.add(BusinessHours(day_of_week=other_day, opens_at='09:00', closes_at='18:00'))
    _set_business_hours_for_today(db, None, None)
    db.session.commit()

    resp = client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 1}]))

    assert resp.status_code == 400
    assert 'no atendemos' in resp.get_json()['message'].lower()
    assert Order.query.count() == 0


def test_create_order_midnight_crossing_now_inside_hours_is_allowed(client, db, order_payload, monkeypatch):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    _set_business_hours_for_today(db, '18:00', '02:00')
    _freeze_time_of_day(monkeypatch, hour=1, minute=0)  # 01:00 - inside 18:00-02:00

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], requestedTime='01:00'))

    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True


def test_create_order_midnight_crossing_now_outside_hours_is_blocked(client, db, order_payload, monkeypatch):
    _register_owner(client)
    product = _create_product(db, stock_quantity=None)
    _set_business_hours_for_today(db, '18:00', '02:00')
    _freeze_time_of_day(monkeypatch, hour=14, minute=0)  # 14:00 - outside 18:00-02:00

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1}], requestedTime='19:00'))

    assert resp.status_code == 400
    assert Order.query.count() == 0


# --- cash_payment_summary(): the shared helper behind the three "vuelto" surfaces ---
# (panel detail, courier WhatsApp message, printed ticket) - a cash shortfall must
# never collapse into an indistinguishable "vuelto $0".

def _cash_order(cash_amount, total_price, payment_method='efectivo', delivery_mode='retira', **overrides):
    defaults = dict(customer_name='Cliente', phone='56911112222', delivery_mode=delivery_mode,
                     payment_method=payment_method, cash_amount=cash_amount, total_price=total_price,
                     status='Pending')
    defaults.update(overrides)
    return Order(**defaults)


def test_cash_payment_summary_over_returns_vuelto():
    order = _cash_order(cash_amount=10000, total_price=8000)
    assert cash_payment_summary(order) == {'status': 'over', 'amount': 2000}


def test_cash_payment_summary_exact_returns_zero_no_vuelto():
    order = _cash_order(cash_amount=8000, total_price=8000)
    assert cash_payment_summary(order) == {'status': 'exact', 'amount': 0}


def test_cash_payment_summary_short_returns_the_shortfall_not_zero():
    order = _cash_order(cash_amount=10000, total_price=11690)
    assert cash_payment_summary(order) == {'status': 'short', 'amount': 1690}


def test_cash_payment_summary_none_when_not_paying_cash():
    order = _cash_order(cash_amount=None, total_price=1000, payment_method='transferencia')
    assert cash_payment_summary(order) is None


def test_cash_payment_summary_none_when_no_cash_amount_declared():
    order = _cash_order(cash_amount=None, total_price=1000, payment_method='efectivo')
    assert cash_payment_summary(order) is None


# --- Bug 1 fix, panel detail: three distinct cash-payment states, not two ---

def test_orders_view_shows_exact_cash_payment_as_justo_not_vuelto(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, name='Producto')
    order = _cash_order(cash_amount=1000, total_price=1000)
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=1000))
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'Paga con $1000 · justo' in html
    # Not a blanket "vuelto" absence check - a CSS comment elsewhere on the page
    # legitimately contains that word. The precise positive assertion above is
    # what actually proves the 'exact' branch rendered, not the 'over' one.
    assert 'vuelto $' not in html.lower()


def test_orders_view_shows_shortfall_warning_not_vuelto_zero(client, db):
    # This is the exact reported scenario: total grew (a product added from the
    # panel) past what the customer declared they'd pay with.
    _register_owner(client)
    product = _create_product(db, price=11690, name='Producto')
    order = _cash_order(cash_amount=10000, total_price=11690)
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=11690))
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'FALTAN $1690' in html
    assert 'cash-change-warning' in html
    assert 'vuelto $0' not in html.lower()


# --- Bug 1 fix, courier WhatsApp message ---

def test_courier_message_shows_vuelto_when_cash_exceeds_total(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = _cash_order(cash_amount=10000, total_price=8000, delivery_mode='envio',
                         daily_number=1, status='Confirmed')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=8000))
    db.session.commit()

    message = _build_courier_message(order)

    assert 'paga con $10000, lleva $2000 de vuelto' in message


def test_courier_message_shows_justo_when_cash_equals_total(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = _cash_order(cash_amount=8000, total_price=8000, delivery_mode='envio',
                         daily_number=1, status='Confirmed')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=8000))
    db.session.commit()

    message = _build_courier_message(order)

    assert 'paga con $8000 justo' in message


def test_courier_message_shows_shortfall_warning_not_vuelto_zero(client, db):
    # The most critical of the three surfaces: this is what the courier reads on
    # their phone right before knocking on the door.
    _register_owner(client)
    product = _create_product(db)
    order = _cash_order(cash_amount=10000, total_price=11690, delivery_mode='envio',
                         daily_number=1, status='Confirmed')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=11690))
    db.session.commit()

    message = _build_courier_message(order)

    assert 'OJO: dijo que pagaba con $10000 pero el total es $11690 - faltan $1690' in message
    assert 'vuelto $0' not in message.lower()


# --- Bug 1 fix, printed ticket ---

def _owner_with_printer(db):
    owner = User.query.filter_by(is_owner=True).first()
    owner.printer_ip = '192.168.1.50'
    db.session.commit()
    return owner


def test_print_ticket_shows_vuelto_when_cash_exceeds_total(client, db):
    _register_owner(client)
    owner = _owner_with_printer(db)
    product = _create_product(db)
    order = _cash_order(cash_amount=10000, total_price=8000, daily_number=1, status='Confirmed')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=8000))
    db.session.commit()

    mock_printer = MagicMock()
    with patch('app.catalog.routes.Network', return_value=mock_printer):
        ok, error = _print_order_ticket(order, owner)

    assert ok is True
    printed = ''.join(call.args[0] for call in mock_printer.text.call_args_list)
    assert 'Vuelto: $2000' in printed


def test_print_ticket_shows_shortfall_warning_not_vuelto_zero(client, db):
    _register_owner(client)
    owner = _owner_with_printer(db)
    product = _create_product(db)
    order = _cash_order(cash_amount=10000, total_price=11690, daily_number=1, status='Confirmed')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=11690))
    db.session.commit()

    mock_printer = MagicMock()
    with patch('app.catalog.routes.Network', return_value=mock_printer):
        ok, error = _print_order_ticket(order, owner)

    assert ok is True
    printed = ''.join(call.args[0] for call in mock_printer.text.call_args_list)
    assert 'OJO: dijo que pagaba con $10000 pero el total es $11690' in printed
    assert 'FALTAN $1690' in printed
    assert 'Vuelto: $0' not in printed


# --- Bug 2 fix: gift badge requires product_id match AND price == 0 ---

def test_orders_view_marks_real_gift_item_price_zero(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, name='Plato Principal')
    gift_product = _create_product(db, price=2000, name='Postre de Regalo')
    owner = User.query.filter_by(is_owner=True).first()
    owner.gift_product_id = gift_product.id
    db.session.commit()

    order = _create_order_with_item(db, product)
    db.session.add(OrderItem(order_id=order.id, product_id=gift_product.id,
                              product_name=gift_product.name, quantity=1, price=0))
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'gift-badge' in html
    assert '🎁 Regalo' in html


def test_orders_view_does_not_mark_manually_added_item_of_gift_product_with_real_price(client, db):
    # The exact reported bug: a Cafe americano added by hand from "Editar productos"
    # (real catalog price) happens to be the product configured as the gift.
    _register_owner(client)
    product = _create_product(db, price=1000, name='Plato Principal')
    gift_product = _create_product(db, price=4990, name='Cafe americano')
    owner = User.query.filter_by(is_owner=True).first()
    owner.gift_product_id = gift_product.id
    db.session.commit()

    order = _create_order_with_item(db, product)
    # Same product_id as the configured gift, but a REAL price - exactly what
    # add_order_item() inserts when added by hand from the panel.
    db.session.add(OrderItem(order_id=order.id, product_id=gift_product.id,
                              product_name=gift_product.name, quantity=1, price=4990))
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'class="gift-badge"' not in html
    assert '🎁' not in html
    assert '1× Cafe americano — $4990' in html


def test_orders_view_does_not_mark_unrelated_product_as_gift(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, name='Plato Principal')
    gift_product = _create_product(db, price=2000, name='Postre de Regalo')
    owner = User.query.filter_by(is_owner=True).first()
    owner.gift_product_id = gift_product.id
    db.session.commit()

    # Only the unrelated product is in this order - the gift was never earned/added.
    order = _create_order_with_item(db, product)
    db.session.commit()

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'class="gift-badge"' not in html
    assert '🎁' not in html


# --- "Editar pedido" (merged Editar productos + Ajustar hora) + catalog picker ---

def _create_product_with_category(db, name, category_name, price=1000, subcategory_name=None):
    category = Category.query.filter_by(name=category_name).first()
    if category is None:
        category = Category(name=category_name)
        db.session.add(category)
        db.session.commit()
    subcategory = None
    if subcategory_name:
        subcategory = Subcategory.query.filter_by(name=subcategory_name, category_id=category.id).first()
        if subcategory is None:
            subcategory = Subcategory(name=subcategory_name, category_id=category.id)
            db.session.add(subcategory)
            db.session.commit()
    product = Product(name=name, description='Test', price=price, category_id=category.id,
                       subcategory_id=(subcategory.id if subcategory else None))
    db.session.add(product)
    db.session.commit()
    return product


def _extract_catalog_json(html):
    match = re.search(r'<script type="application/json" id="order-edit-catalog">(.*?)</script>', html, re.S)
    assert match is not None, 'catalog JSON script tag not found'
    return json.loads(match.group(1))


def test_orders_view_catalog_json_embedded_once_regardless_of_order_count(client, db):
    _register_owner(client)
    product = _create_product_with_category(db, 'Café', 'Bebidas')
    _create_order_with_item(db, product)
    _create_order_with_item(db, product)

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    # Two orders on the page, but the catalog blob (and its <script> tag) must
    # appear exactly once - not once per order's own "Editar pedido" section.
    assert html.count('id="order-edit-catalog"') == 1


def test_orders_view_catalog_json_includes_category_and_subcategory_names(client, db):
    _register_owner(client)
    product = _create_product_with_category(db, 'Roll California', 'Sushi', subcategory_name='Rolls fríos')
    _create_order_with_item(db, product)

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    catalog = _extract_catalog_json(html)
    entry = next(p for p in catalog if p['name'] == 'Roll California')
    assert entry['categoryName'] == 'Sushi'
    assert entry['subcategoryName'] == 'Rolls fríos'


def test_orders_view_catalog_json_subcategory_name_is_none_when_product_has_none(client, db):
    _register_owner(client)
    product = _create_product_with_category(db, 'Bebida Suelta', 'Bebidas')
    _create_order_with_item(db, product)

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    catalog = _extract_catalog_json(html)
    entry = next(p for p in catalog if p['name'] == 'Bebida Suelta')
    assert entry['subcategoryId'] is None
    assert entry['subcategoryName'] is None


def test_orders_view_catalog_serialization_does_not_n_plus_1_on_category(client, db):
    """Regression guard: Product.category/subcategory are lazy='select' by default -
    without joinedload, each distinct category fires its own query the first time
    it's touched. With joinedload, the query count stays flat no matter how many
    distinct categories the catalog spans."""
    _register_owner(client)
    _create_order_with_item(db, _create_product_with_category(db, 'Base', 'CategoriaBase'))

    queries = []

    def _log_query(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    engine = _db.engine

    event.listen(engine, 'before_cursor_execute', _log_query)
    try:
        resp_few = client.get('/admin/orders')
    finally:
        event.remove(engine, 'before_cursor_execute', _log_query)
    assert resp_few.status_code == 200
    count_with_one_category = len(queries)

    for i in range(10):
        _create_product_with_category(db, f'Producto {i}', f'Categoria {i}', subcategory_name=f'Sub {i}')

    queries.clear()
    event.listen(engine, 'before_cursor_execute', _log_query)
    try:
        resp_many = client.get('/admin/orders')
    finally:
        event.remove(engine, 'before_cursor_execute', _log_query)
    assert resp_many.status_code == 200
    count_with_eleven_categories = len(queries)

    # 10 more products, each in its own new category AND subcategory, must not add
    # ~10-20 extra queries - joinedload folds category/subcategory into the same
    # single products query via JOINs, regardless of how many distinct rows exist.
    assert count_with_eleven_categories - count_with_one_category <= 1


def test_orders_view_edit_order_groups_products_and_time_forms(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = _create_order_with_item(db, product)

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert 'Editar pedido' in html
    # The old, separate summaries are gone - merged into the one button above.
    assert 'Editar productos' not in html
    assert 'Ajustar hora (sobrecupo' not in html

    edit_pedido_index = html.index('Editar pedido')
    add_item_action = f'/admin/orders/{order.id}/items/add'
    update_time_action = f'/admin/orders/{order.id}/update-time'
    # Both forms' routes are nested inside "Editar pedido", not loose elsewhere.
    assert html.index(add_item_action) > edit_pedido_index
    assert html.index(update_time_action) > edit_pedido_index


def test_orders_view_edit_order_has_no_plain_select_for_products(client, db):
    # The flat <select> with the whole catalog is gone - replaced by the search+group
    # picker fed from the embedded JSON.
    _register_owner(client)
    product = _create_product(db)
    _create_order_with_item(db, product)

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    assert '<select name="product_id"' not in html
    assert 'class="product-picker-search"' in html
    assert 'name="product_id" class="product-picker-selected-id"' in html


# --- add_order_item() with product options - reuses _resolve_selected_options from
# main.routes (same function create_order() uses), not a reimplementation ---

def _create_product_with_options(db, name='Café americano', price=4990):
    category = Category(name='Bebidas')
    db.session.add(category)
    db.session.commit()
    product = Product(name=name, description='Test', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    size_group = ProductOptionGroup(product_id=product.id, name='Tamaño', required=True, multi_select=False)
    db.session.add(size_group)
    db.session.commit()
    mediano = ProductOption(group_id=size_group.id, name='Mediano', price_delta=0)
    grande = ProductOption(group_id=size_group.id, name='Grande', price_delta=1790)
    db.session.add_all([mediano, grande])
    db.session.commit()
    return product, size_group, mediano, grande


def test_add_order_item_with_priced_option_charges_base_plus_delta(client, db):
    # The reported bug, exactly: Cafe americano Grande added from the panel must cost
    # base + delta ($4990 + $1790), not just the base price.
    _register_owner(client)
    product, size_group, mediano, grande = _create_product_with_options(db)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))

    resp = client.post(f'/admin/orders/{order.id}/items/add', data={
        'product_id': product.id, 'quantity': 1, 'option_ids': [grande.id],
    })

    assert resp.status_code == 302
    item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
    assert item is not None
    assert item.price == 4990 + 1790
    options = OrderItemOption.query.filter_by(order_item_id=item.id).all()
    assert len(options) == 1
    assert options[0].name == 'Grande'
    assert options[0].price_delta == 1790


def test_add_order_item_missing_required_option_is_rejected(client, db):
    _register_owner(client)
    product, size_group, mediano, grande = _create_product_with_options(db)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))

    resp = client.post(f'/admin/orders/{order.id}/items/add', data={
        'product_id': product.id, 'quantity': 1,
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'Elige una opción para' in resp.data.decode()
    assert OrderItem.query.filter_by(order_id=order.id, product_id=product.id).count() == 0


def test_add_order_item_two_options_in_single_select_group_is_rejected(client, db):
    _register_owner(client)
    product, size_group, mediano, grande = _create_product_with_options(db)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))

    resp = client.post(f'/admin/orders/{order.id}/items/add', data={
        'product_id': product.id, 'quantity': 1, 'option_ids': [mediano.id, grande.id],
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'Solo puedes elegir una opción para' in resp.data.decode()
    assert OrderItem.query.filter_by(order_id=order.id, product_id=product.id).count() == 0


def test_add_order_item_without_options_still_works_like_before(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, name='Bebida Simple', stock_quantity=None)
    order = _create_order_with_item(db, _create_product(db, stock_quantity=None))

    resp = client.post(f'/admin/orders/{order.id}/items/add', data={
        'product_id': product.id, 'quantity': 2,
    })

    assert resp.status_code == 302
    item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
    assert item is not None
    assert item.price == 1000
    assert item.quantity == 2
    assert OrderItemOption.query.filter_by(order_item_id=item.id).count() == 0


def test_add_order_item_with_priced_option_recalculates_order_total(client, db):
    _register_owner(client)
    product, size_group, mediano, grande = _create_product_with_options(db)
    order = _create_order_with_item(db, _create_product(db, price=1000, stock_quantity=None))  # total starts at 1000

    client.post(f'/admin/orders/{order.id}/items/add', data={
        'product_id': product.id, 'quantity': 1, 'option_ids': [grande.id],
    })

    db.session.refresh(order)
    assert order.total_price == 1000 + 4990 + 1790


# --- catalog JSON includes optionGroups, serialized without N+1 ---

def test_orders_view_catalog_json_includes_option_groups(client, db):
    _register_owner(client)
    product, size_group, mediano, grande = _create_product_with_options(db)
    _create_order_with_item(db, product)

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    catalog = _extract_catalog_json(html)
    entry = next(p for p in catalog if p['name'] == 'Café americano')
    assert len(entry['optionGroups']) == 1
    group = entry['optionGroups'][0]
    assert group['name'] == 'Tamaño'
    assert group['required'] is True
    assert group['multiSelect'] is False
    option_deltas = {o['name']: o['priceDelta'] for o in group['options']}
    assert option_deltas == {'Mediano': 0, 'Grande': 1790}


def test_orders_view_catalog_json_option_groups_empty_for_product_without_options(client, db):
    _register_owner(client)
    product = _create_product(db, name='Sin Variantes')
    _create_order_with_item(db, product)

    resp = client.get('/admin/orders')
    html = resp.data.decode()

    catalog = _extract_catalog_json(html)
    entry = next(p for p in catalog if p['name'] == 'Sin Variantes')
    assert entry['optionGroups'] == []


def test_orders_view_catalog_serialization_does_not_n_plus_1_on_option_groups(client, db):
    """Regression guard: Product.option_groups (and each group's .options) are
    lazy='select' by default - without selectinload, each product/group fires its own
    query the first time it's touched. With selectinload, the query count stays flat
    no matter how many products carry option groups."""
    _register_owner(client)
    product, _group, _mediano, _grande = _create_product_with_options(db)
    _create_order_with_item(db, product)

    queries = []

    def _log_query(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    engine = _db.engine

    event.listen(engine, 'before_cursor_execute', _log_query)
    try:
        resp_one = client.get('/admin/orders')
    finally:
        event.remove(engine, 'before_cursor_execute', _log_query)
    assert resp_one.status_code == 200
    count_with_one_product = len(queries)

    for i in range(10):
        _create_product_with_options(db, name=f'Producto {i}', price=1000)

    queries.clear()
    event.listen(engine, 'before_cursor_execute', _log_query)
    try:
        resp_many = client.get('/admin/orders')
    finally:
        event.remove(engine, 'before_cursor_execute', _log_query)
    assert resp_many.status_code == 200
    count_with_eleven_products = len(queries)

    # 10 more products, each with its own option group and two options, must not add
    # ~20+ extra queries - selectinload batches option_groups/options into a couple
    # of extra queries total, regardless of how many products/groups exist.
    assert count_with_eleven_products - count_with_one_product <= 2
