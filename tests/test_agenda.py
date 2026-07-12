from datetime import datetime, timedelta

from app.catalog.routes import _build_agenda_blocks
from app.models import BUSINESS_TZ, BusinessHours, Category, Order, OrderItem, Product, User


def _future_time_str(minutes_ahead=60):
    """A requested_time in a block that hasn't happened yet."""
    return (datetime.now(BUSINESS_TZ) + timedelta(minutes=minutes_ahead)).strftime('%H:%M')


def _past_time_str(minutes_ago=60):
    """A requested_time in a block that has already happened."""
    return (datetime.now(BUSINESS_TZ) - timedelta(minutes=minutes_ago)).strftime('%H:%M')


def _order(requested_time=None, payment_status='pending'):
    """An in-memory (unsaved) Order - _build_agenda_blocks only reads
    requested_time/payment_status, so there's no need to hit the DB for these."""
    return Order(requested_time=requested_time, payment_status=payment_status,
                 customer_name='Cliente', phone='56911112222', delivery_mode='retira',
                 total_price=1000, status='Confirmed')


# --- _build_agenda_blocks: pure grouping logic ---

def test_order_lands_in_the_block_that_contains_its_time():
    order = _order(requested_time='19:25')

    blocks, unscheduled = _build_agenda_blocks([order], block_minutes=20,
                                                opens_at='18:00', closes_at='22:00', now_str='12:00')

    assert unscheduled == []
    matching = [b for b in blocks if order in b['orders']]
    assert len(matching) == 1
    assert matching[0]['label_start'] == '19:20'
    assert matching[0]['label_end'] == '19:40'


def test_two_orders_in_same_block_sorted_by_exact_time():
    later = _order(requested_time='19:35')
    earlier = _order(requested_time='19:22')

    blocks, _ = _build_agenda_blocks([later, earlier], block_minutes=20,
                                      opens_at='18:00', closes_at='22:00', now_str='12:00')

    block = next(b for b in blocks if b['label_start'] == '19:20')
    assert block['orders'] == [earlier, later]  # exact-time order, not insertion order


def test_block_with_no_orders_is_empty_not_missing():
    blocks, _ = _build_agenda_blocks([], block_minutes=20,
                                      opens_at='18:00', closes_at='19:00', now_str='12:00')

    assert len(blocks) == 3  # 18:00-18:20, 18:20-18:40, 18:40-19:00
    assert all(b['orders'] == [] for b in blocks)


def test_order_outside_business_hours_goes_to_unscheduled():
    order = _order(requested_time='23:50')  # outside 18:00-22:00

    blocks, unscheduled = _build_agenda_blocks([order], block_minutes=20,
                                                opens_at='18:00', closes_at='22:00', now_str='12:00')

    assert unscheduled == [order]
    assert all(order not in b['orders'] for b in blocks)


def test_order_without_requested_time_goes_to_unscheduled():
    order = _order(requested_time=None)

    blocks, unscheduled = _build_agenda_blocks([order], block_minutes=20,
                                                opens_at='18:00', closes_at='22:00', now_str='12:00')

    assert unscheduled == [order]


def test_block_size_20_vs_30_changes_boundaries():
    order = _order(requested_time='19:25')

    blocks_20, _ = _build_agenda_blocks([order], block_minutes=20,
                                         opens_at='18:00', closes_at='22:00', now_str='12:00')
    blocks_30, _ = _build_agenda_blocks([order], block_minutes=30,
                                         opens_at='18:00', closes_at='22:00', now_str='12:00')

    block_20 = next(b for b in blocks_20 if order in b['orders'])
    block_30 = next(b for b in blocks_30 if order in b['orders'])
    assert (block_20['label_start'], block_20['label_end']) == ('19:20', '19:40')
    assert (block_30['label_start'], block_30['label_end']) == ('19:00', '19:30')


def test_blocks_before_now_are_marked_past():
    blocks, _ = _build_agenda_blocks([], block_minutes=20,
                                      opens_at='18:00', closes_at='22:00', now_str='19:00')

    first_block = blocks[0]  # 18:00-18:20, ends before 19:00
    assert first_block['is_past'] is True
    last_block = blocks[-1]  # 21:40-22:00, ends after 19:00
    assert last_block['is_past'] is False


# --- midnight crossing (opens_at > closes_at, e.g. 18:00-02:00 - Lourdes closes late) ---

def test_order_before_midnight_lands_in_its_block():
    order = _order(requested_time='20:00')

    blocks, unscheduled = _build_agenda_blocks([order], block_minutes=30,
                                                opens_at='18:00', closes_at='02:00', now_str='12:00')

    assert unscheduled == []
    matching = next(b for b in blocks if order in b['orders'])
    assert (matching['label_start'], matching['label_end']) == ('20:00', '20:30')


def test_order_after_midnight_lands_in_its_block_not_unscheduled():
    # 00:30 is 390 minutes after 18:00 opens_at -> block index 13 (30-min blocks),
    # which is exactly the +1440 wraparound path (00:30 alone, un-normalized, looks
    # earlier than 18:00 and would otherwise misfire as "before opening").
    order = _order(requested_time='00:30')

    blocks, unscheduled = _build_agenda_blocks([order], block_minutes=30,
                                                opens_at='18:00', closes_at='02:00', now_str='12:00')

    assert unscheduled == []
    matching = next(b for b in blocks if order in b['orders'])
    assert (matching['label_start'], matching['label_end']) == ('00:30', '01:00')


def test_order_after_closing_past_midnight_goes_to_unscheduled():
    order = _order(requested_time='03:00')  # after the 02:00 close, still "de madrugada"

    blocks, unscheduled = _build_agenda_blocks([order], block_minutes=30,
                                                opens_at='18:00', closes_at='02:00', now_str='12:00')

    assert unscheduled == [order]
    assert all(order not in b['orders'] for b in blocks)


def test_is_past_at_00_45_keeps_pre_midnight_blocks_past_and_post_midnight_future():
    # The critical case: at 00:45, a 20:00-20:30 block must read as past (it already
    # happened tonight), and a 01:00-01:30 block must read as future (it hasn't
    # happened yet) - this only works if "now" (00:45) is ALSO shifted to 1485
    # minutes (00:45 + 1440), landing after 20:00-20:30's timeline position (1200-1230)
    # and before 01:00-01:30's (1500-1530). Un-normalized, 00:45 (45) would look
    # earlier than everything and mark the whole night as "still to come".
    blocks, _ = _build_agenda_blocks([], block_minutes=30,
                                      opens_at='18:00', closes_at='02:00', now_str='00:45')

    early_block = next(b for b in blocks if (b['label_start'], b['label_end']) == ('20:00', '20:30'))
    late_block = next(b for b in blocks if (b['label_start'], b['label_end']) == ('01:00', '01:30'))
    assert early_block['is_past'] is True
    assert late_block['is_past'] is False


def test_is_past_at_19_00_no_post_midnight_block_has_happened_yet():
    blocks, _ = _build_agenda_blocks([], block_minutes=30,
                                      opens_at='18:00', closes_at='02:00', now_str='19:00')

    late_block = next(b for b in blocks if (b['label_start'], b['label_end']) == ('01:00', '01:30'))
    assert late_block['is_past'] is False


# --- /admin/agenda route ---

def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _create_product(db, price=1000, name='Producto'):
    category = Category(name='Categoria')
    db.session.add(category)
    db.session.commit()
    product = Product(name=name, description='Test', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


def _create_order(db, product, requested_time, status='Confirmed', daily_number=None,
                   customer_name='Cliente', payment_status='pending'):
    order = Order(customer_name=customer_name, phone='56911112222', delivery_mode='retira',
                  payment_method='efectivo', total_price=product.price, status=status,
                  requested_time=requested_time, daily_number=daily_number, payment_status=payment_status)
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=product.price))
    db.session.commit()
    return order


def _set_business_hours_for_today(db, opens_at='09:00', closes_at='23:00'):
    today_weekday = datetime.now(BUSINESS_TZ).weekday()
    db.session.add(BusinessHours(day_of_week=today_weekday, opens_at=opens_at, closes_at=closes_at))
    db.session.commit()


def test_agenda_route_only_shows_confirmed_orders(client, db):
    _register_owner(client)
    _set_business_hours_for_today(db)
    product = _create_product(db)
    future = _future_time_str()
    # Confirmed lands in a future (or unscheduled) block, either way rendered in
    # full - Pending/Cancelled must never even be queried into the page at all.
    _create_order(db, product, future, status='Confirmed', daily_number=1, customer_name='ConfirmadoVisible')
    _create_order(db, product, future, status='Pending', customer_name='PendienteInvisible')
    _create_order(db, product, future, status='Cancelled', customer_name='CanceladoInvisible')

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    assert resp.status_code == 200
    assert 'ConfirmadoVisible' in html
    assert 'PendienteInvisible' not in html
    assert 'CanceladoInvisible' not in html


def test_agenda_route_shows_daily_number_on_card(client, db):
    _register_owner(client)
    _set_business_hours_for_today(db)
    product = _create_product(db)
    _create_order(db, product, _future_time_str(), status='Confirmed', daily_number=7, customer_name='ConNumero')

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    assert '#7' in html
    assert 'ConNumero' in html


def test_agenda_route_marks_future_empty_block_as_libre(client, db):
    _register_owner(client)
    _set_business_hours_for_today(db)  # no orders at all today

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    assert 'libre' in html


def test_agenda_route_shows_free_blocks_after_the_one_with_an_order(client, db):
    """Regression: reported bug where only the block with the order rendered and
    every later free block of the day silently disappeared."""
    _register_owner(client)
    _set_business_hours_for_today(db, opens_at='09:00', closes_at='23:00')
    owner = User.query.filter_by(is_owner=True).first()
    owner.agenda_block_minutes = 5
    db.session.commit()
    product = _create_product(db)
    order_time = _future_time_str(30)  # well before closing, room for later free blocks
    _create_order(db, product, order_time, status='Confirmed', daily_number=1, customer_name='ConPedido')

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    assert 'ConPedido' in html
    assert html.count('agenda-block-free') > 1  # more than just one lonely free block
    assert 'libre' in html


def test_agenda_route_past_block_with_orders_shows_order_details(client, db):
    """Paso 2c fix: a past block that HAS orders must render them in full - it must
    never collapse into a summary that hides an unpaid order."""
    _register_owner(client)
    _set_business_hours_for_today(db, opens_at='00:00', closes_at='23:59')
    product = _create_product(db)
    _create_order(db, product, _past_time_str(60), status='Confirmed', daily_number=9,
                   customer_name='PedidoDelPasado', payment_status='pending')

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    assert 'PedidoDelPasado' in html
    assert '#9' in html


def test_agenda_route_past_empty_block_is_not_rendered(client, db):
    """Paso 2c fix: a past block with NO orders can't be agendado into anymore and
    hides no debt, so it must not take up any space on the page."""
    _register_owner(client)
    two_hours_ago = (datetime.now(BUSINESS_TZ) - timedelta(hours=2)).strftime('%H:%M')
    one_hour_ago = (datetime.now(BUSINESS_TZ) - timedelta(hours=1)).strftime('%H:%M')
    db.session.add(BusinessHours(day_of_week=datetime.now(BUSINESS_TZ).weekday(),
                                  opens_at=two_hours_ago, closes_at=one_hour_ago))
    db.session.commit()
    owner = User.query.filter_by(is_owner=True).first()
    owner.agenda_block_minutes = 60
    db.session.commit()
    # No orders created - the single 60-min block spanning this hour is empty and past.

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    assert f'{two_hours_ago}–{one_hour_ago}' not in html


def test_agenda_route_unscheduled_zone_for_null_requested_time(client, db):
    _register_owner(client)
    _set_business_hours_for_today(db)
    product = _create_product(db)
    _create_order(db, product, None, status='Confirmed', daily_number=3, customer_name='SinHora')

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    assert 'Sin hora o fuera de horario' in html
    assert 'SinHora' in html


def test_agenda_route_time_outside_hours_goes_to_unscheduled_zone(client, db):
    _register_owner(client)
    _set_business_hours_for_today(db, opens_at='09:00', closes_at='23:00')
    product = _create_product(db)
    _create_order(db, product, '23:55', status='Confirmed', daily_number=4, customer_name='FueraDeHorario')

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    assert 'Sin hora o fuera de horario' in html
    assert 'FueraDeHorario' in html


def test_agenda_route_uses_owners_configured_block_size(client, db):
    _register_owner(client)
    _set_business_hours_for_today(db, opens_at='09:00', closes_at='23:00')
    owner = User.query.filter_by(is_owner=True).first()
    owner.agenda_block_minutes = 30
    db.session.commit()
    product = _create_product(db)
    _create_order(db, product, '10:15', status='Confirmed', daily_number=1, customer_name='Bloque30')

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    # A block with an order always renders its header, past or future - this alone
    # proves the route used the owner's 30-min size, since the 10-min default would
    # never produce a single 10:00-10:30 block, only three separate 10-min ones.
    assert '10:00–10:30' in html


def test_agenda_mark_paid_button_only_on_pending_payment(client, db):
    _register_owner(client)
    _set_business_hours_for_today(db)
    product = _create_product(db)
    future = _future_time_str()
    unpaid = _create_order(db, product, future, status='Confirmed', daily_number=1,
                            customer_name='SinPagar', payment_status='pending')
    paid = _create_order(db, product, future, status='Confirmed', daily_number=2,
                          customer_name='YaPagado', payment_status='paid')

    resp = client.get('/admin/agenda')
    html = resp.data.decode()

    assert f'/admin/orders/{unpaid.id}/mark-paid' in html
    assert f'/admin/orders/{paid.id}/mark-paid' not in html


def test_mark_paid_from_agenda_redirects_back_to_agenda(client, db):
    _register_owner(client)
    _set_business_hours_for_today(db)
    product = _create_product(db)
    order = _create_order(db, product, _future_time_str(), status='Confirmed', daily_number=1,
                           customer_name='Cliente', payment_status='pending')

    resp = client.post(f'/admin/orders/{order.id}/mark-paid', data={'next': '/admin/agenda'})

    assert resp.status_code == 302
    assert resp.location == '/admin/agenda'
    db.session.refresh(order)
    assert order.payment_status == 'paid'
