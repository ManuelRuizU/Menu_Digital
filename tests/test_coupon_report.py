from datetime import date, datetime, timedelta

from app.coupon_report import build_report, coupon_report_command, coupon_state, potential_saving
from app.models import Category, Coupon, CouponRedemption, Order, OrderItem, Product


def _product(db, price=1000):
    category = Category(name='Categoria')
    db.session.add(category)
    db.session.commit()
    product = Product(name='Producto', description='', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


def _order(db, product, quantity=1, coupon=None, status='Pending', days_ago=1, phone='56911112222'):
    order = Order(customer_name='Ana', phone=phone, delivery_mode='retira', payment_method='efectivo',
                  total_price=product.price * quantity, status=status, coupon_id=coupon.id if coupon else None,
                  created_at=datetime.utcnow() - timedelta(days=days_ago))
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                             quantity=quantity, price=product.price))
    if coupon:
        db.session.add(CouponRedemption(coupon_id=coupon.id, order_id=order.id, phone_digits=phone,
                                        created_at=order.created_at))
    db.session.commit()
    return order


def _coupon(db, **fields):
    values = dict(code='DULCE', discount_percent=10, scope='order', is_active=True, show_in_banner=True)
    values.update(fields)
    coupon = Coupon(**values)
    db.session.add(coupon)
    db.session.commit()
    return coupon


def test_coupon_state_follows_validate_coupon_order(db):
    today = date(2026, 10, 29)
    assert coupon_state(Coupon(code='A', is_active=False), today) == 'inactivo'
    assert coupon_state(Coupon(code='B', is_active=True, valid_from=date(2026, 11, 1)), today) == 'aún no vigente'
    assert coupon_state(Coupon(code='C', is_active=True, valid_until=date(2026, 10, 28)), today) == 'vencido'
    assert coupon_state(Coupon(code='D', is_active=True, valid_until=today), today) == 'vigente'


def test_potential_saving_respects_minimum_and_scope(db):
    product = _product(db, price=4000)
    small = _order(db, product, quantity=1)
    big = _order(db, product, quantity=3)
    coupon = _coupon(db, min_order_amount=10000)
    assert potential_saving(coupon, small) == (False, 0)
    assert potential_saving(coupon, big) == (True, 1200)
    gift = _coupon(db, code='REGALO', kind='product', discount_percent=None, gift_product_id=product.id)
    assert potential_saving(gift, big) == (True, 0)


def test_potential_saving_skips_customer_who_already_used_it(db):
    product = _product(db, price=5000)
    coupon = _coupon(db, max_uses_per_customer=1)
    _order(db, product, coupon=coupon, days_ago=3)
    later = _order(db, product, days_ago=1)
    assert potential_saving(coupon, later) == (False, 0)
    other = _order(db, product, days_ago=1, phone='56933334444')
    assert potential_saving(coupon, other) == (True, 500)


def test_report_counts_window_coupon_use_and_missed_orders(db):
    product = _product(db, price=5000)
    coupon = _coupon(db)
    _coupon(db, code='SECRETO', show_in_banner=False, discount_percent=50)
    _order(db, product, coupon=coupon, status='Confirmed')
    _order(db, product, quantity=2)
    _order(db, product, status='Cancelled')
    _order(db, product, days_ago=45)
    report = build_report(days=30)
    assert report['orders_total'] == 3
    assert report['orders_valid'] == 2
    assert report['orders_with_coupon'] == 1
    assert report['confirmed_with_coupon'] == 1
    # Only the public coupon counts as a missed chance - nobody could see SECRETO.
    assert report['missed'] == 1
    assert report['missed_saving'] == 1000
    assert report['missed_by_code'] == {'DULCE': 1}


def test_report_never_writes(app, db):
    product = _product(db)
    _coupon(db)
    _order(db, product)
    db.session.commit()
    result = app.test_cli_runner().invoke(coupon_report_command, ['--days', '30'])
    assert result.exit_code == 0, result.output
    assert 'DULCE: -10% · vigente · público (banner)' in result.output
    assert 'con cupón: 0 de 1' in result.output
    assert not db.session.dirty and not db.session.new


def test_dates_are_in_santiago_time(app, db):
    # 22:00 on 01/11 in Santiago is 01:00 on 02/11 in UTC (what the database keeps): the
    # last use must read as the 1st, inside a coupon that ends that day.
    product = _product(db)
    coupon = _coupon(db, valid_until=date(2026, 11, 1))
    order = _order(db, product, coupon=coupon)
    order.created_at = datetime(2026, 11, 2, 1, 0)
    CouponRedemption.query.filter_by(order_id=order.id).one().created_at = datetime(2026, 11, 2, 1, 0)
    db.session.commit()
    report = build_report(days=30, now=datetime(2026, 11, 2, 2, 0))
    assert report['today'] == date(2026, 11, 1)
    row = report['coupons'][0]
    assert row['state'] == 'vigente'
    assert row['last_use'].strftime('%d/%m/%Y %H:%M') == '01/11/2026 22:00'
    assert report['end'].strftime('%d/%m %H:%M') == '01/11 23:00'
    result = app.test_cli_runner().invoke(coupon_report_command, ['--days', '30'])
    assert 'último: 01/11/2026 22:00' in result.output
    assert 'vigencia … a 01/11/2026' in result.output


def test_report_gross_sales_discount_share_and_tickets(db):
    product = _product(db, price=5000)
    coupon = _coupon(db)
    with_coupon = _order(db, product, quantity=2, coupon=coupon)
    with_coupon.total_price, with_coupon.discount_amount = 9000, 1000
    _order(db, product, quantity=1)
    _order(db, product, quantity=3)
    cancelled = _order(db, product, quantity=4, coupon=coupon, status='Cancelled')
    cancelled.discount_amount = 2000
    db.session.commit()
    report = build_report(days=30)
    # 10000 (9000 paid + 1000 coupon) + 5000 + 15000; the cancelled order doesn't count.
    assert report['gross_sales'] == 30000
    assert report['discount_total'] == 1000
    assert report['discount_percent'] == 3.3
    assert report['ticket_with_coupon'] == 9000
    assert report['ticket_without_coupon'] == 10000


def test_report_with_nothing_sold_has_no_division_errors(db):
    report = build_report(days=7)
    assert (report['gross_sales'], report['discount_percent'],
            report['ticket_with_coupon'], report['ticket_without_coupon']) == (0, 0, None, None)


def test_compare_days_reports_the_same_numbers_for_an_earlier_window(app, db):
    product = _product(db, price=5000)
    coupon = _coupon(db)
    now = datetime(2026, 11, 2, 12, 0)
    for days_ago, quantity, used in ((1, 2, True), (2, 1, False), (8, 4, False), (12, 1, False)):
        order = _order(db, product, quantity=quantity, coupon=coupon if used else None)
        order.created_at = now - timedelta(days=days_ago)
    db.session.commit()
    report = build_report(days=3, now=now, compare_days=7)
    assert (report['orders_valid'], report['orders_with_coupon'], report['gross_sales']) == (2, 1, 15000)
    previous = report['previous']
    # Only the order from 8 days ago falls in [10, 7) days ago; the one from 12 doesn't.
    assert (previous['orders_valid'], previous['orders_with_coupon'], previous['gross_sales']) == (1, 0, 20000)
    assert previous['ticket_without_coupon'] == 20000
    assert previous['ticket_with_coupon'] is None
    assert previous['start'].strftime('%d/%m %H:%M') == '23/10 09:00'
    assert previous['end'].strftime('%d/%m %H:%M') == '26/10 09:00'
    assert 'previous' not in build_report(days=3, now=now)

    result = app.test_cli_runner().invoke(coupon_report_command, ['--days', '3', '--compare-days', '7'])
    assert result.exit_code == 0, result.output
    assert 'Comparación: 3 días, 7 días antes' in result.output
    assert 'ventas brutas:' in result.output and 'ticket promedio: con cupón' in result.output
    assert app.test_cli_runner().invoke(coupon_report_command, ['--compare-days', '0']).exit_code != 0
