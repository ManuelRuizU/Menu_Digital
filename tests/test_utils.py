from datetime import date, datetime, timedelta

from app.models import Order
from app.utils import day_range_utc


# --- winter (UTC-4) ---

def test_day_range_utc_winter_midnight_is_04_utc():
    start_utc, end_utc = day_range_utc(date(2026, 7, 15))

    # Santiago is UTC-4 in July (winter, no DST) - midnight local = 04:00 UTC same day.
    assert start_utc == datetime(2026, 7, 15, 4, 0, 0)
    assert end_utc == datetime(2026, 7, 16, 4, 0, 0)
    assert end_utc - start_utc == timedelta(hours=24)


# --- summer (UTC-3, DST) - the test that justifies not hardcoding the offset ---

def test_day_range_utc_summer_midnight_is_03_utc_not_04():
    start_utc, end_utc = day_range_utc(date(2026, 1, 15))

    # Santiago is UTC-3 in January (DST) - midnight local = 03:00 UTC same day, NOT
    # 04:00. If the offset were ever hardcoded to -4, this would silently drift an
    # hour every summer; ZoneInfo resolves it correctly from the date instead.
    assert start_utc == datetime(2026, 1, 15, 3, 0, 0)
    assert end_utc == datetime(2026, 1, 16, 3, 0, 0)
    assert end_utc - start_utc == timedelta(hours=24)


# --- the DST transition day itself: not a 24h day in real time ---

def test_day_range_utc_on_fall_back_transition_day_is_25_hours():
    # 2026-04-05 is when Chile sets clocks back from UTC-3 to UTC-4 (DST ends).
    # Midnight local on 2026-04-04 is still UTC-3 (03:00 UTC); midnight local on
    # 2026-04-05 is already UTC-4 (04:00 UTC) - so the calendar day of 2026-04-04
    # spans 25 real hours, not 24. day_range_utc still returns a coherent,
    # non-overlapping [start, end) range - it's just wider than usual by an hour.
    start_utc, end_utc = day_range_utc(date(2026, 4, 4))

    assert start_utc == datetime(2026, 4, 4, 3, 0, 0)
    assert end_utc == datetime(2026, 4, 5, 4, 0, 0)
    assert end_utc - start_utc == timedelta(hours=25)


def test_day_range_utc_on_spring_forward_transition_day_is_23_hours():
    # 2026-09-07 is when Chile sets clocks forward from UTC-4 to UTC-3 (DST starts).
    # The calendar day of 2026-09-06 spans only 23 real hours for the same reason,
    # in the opposite direction.
    start_utc, end_utc = day_range_utc(date(2026, 9, 6))

    assert start_utc == datetime(2026, 9, 6, 4, 0, 0)
    assert end_utc == datetime(2026, 9, 7, 3, 0, 0)
    assert end_utc - start_utc == timedelta(hours=23)


# --- ties the function to how orders() actually filters ---

def _create_order_at(db, created_at):
    order = Order(customer_name='Cliente', phone='56911112222', delivery_mode='retira',
                  payment_method='efectivo', total_price=1000, status='Pending',
                  created_at=created_at)
    db.session.add(order)
    db.session.commit()
    return order


def test_day_range_utc_matches_orders_filter_boundaries(db):
    # Same winter day as test 1: [2026-07-15 04:00 UTC, 2026-07-16 04:00 UTC).
    start_utc, end_utc = day_range_utc(date(2026, 7, 15))

    inside_early = _create_order_at(db, start_utc)  # exactly at start - included (>=)
    inside_late = _create_order_at(db, end_utc - timedelta(seconds=1))  # just before end
    before = _create_order_at(db, start_utc - timedelta(seconds=1))  # 1s before - excluded
    at_end = _create_order_at(db, end_utc)  # exactly at end - excluded (< end, exclusive)

    matched_ids = {order.id for order in
                   Order.query.filter(Order.created_at >= start_utc, Order.created_at < end_utc).all()}

    assert matched_ids == {inside_early.id, inside_late.id}
    assert before.id not in matched_ids
    assert at_end.id not in matched_ids
