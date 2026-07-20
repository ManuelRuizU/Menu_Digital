from datetime import datetime

from app.models import BUSINESS_TZ, BusinessHours, User


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _today_weekday():
    return datetime.now(BUSINESS_TZ).weekday()


def test_new_user_starts_with_default_agenda_block_minutes(client, db):
    _register_owner(client)

    owner = User.query.filter_by(is_owner=True).first()
    assert owner.agenda_block_minutes == 10


def test_agenda_block_minutes_saves_valid_value_as_int(client, db):
    _register_owner(client)

    resp = client.post('/admin/business-profile', data={'agenda_block_minutes': '20'})

    assert resp.status_code == 302
    owner = User.query.filter_by(is_owner=True).first()
    assert owner.agenda_block_minutes == 20
    assert isinstance(owner.agenda_block_minutes, int)


def test_agenda_block_minutes_ignores_invalid_values(client, db):
    _register_owner(client)
    owner = User.query.filter_by(is_owner=True).first()
    owner.agenda_block_minutes = 30
    db.session.commit()

    for invalid in ('abc', '7', '999', ''):
        resp = client.post('/admin/business-profile', data={'agenda_block_minutes': invalid})
        assert resp.status_code == 302
        db.session.refresh(owner)
        assert owner.agenda_block_minutes == 30  # unchanged, whatever was rejected


def test_agenda_block_minutes_select_renders_all_options_with_current_selected(client, db):
    _register_owner(client)
    owner = User.query.filter_by(is_owner=True).first()
    owner.agenda_block_minutes = 30
    db.session.commit()

    resp = client.get('/admin')
    html = resp.data.decode()

    for minutes in (5, 10, 15, 20, 30, 60):
        assert f'<option value="{minutes}"' in html
    assert '<option value="30" selected>30 min</option>' in html


# --- update_business_hours: reject opens_at == closes_at, allow real overnight crossing ---

def test_update_business_hours_rejects_opens_equals_closes(client, db):
    _register_owner(client)
    today = _today_weekday()
    other_day = (today + 1) % 7

    resp = client.post('/admin/business-hours', data={
        f'opens_{today}': '19:00', f'closes_{today}': '19:00',
        f'opens_{other_day}': '09:00', f'closes_{other_day}': '18:00',
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'no puede ser igual al cierre' in resp.data.decode()

    today_hours = BusinessHours.query.filter_by(day_of_week=today).first()
    other_hours = BusinessHours.query.filter_by(day_of_week=other_day).first()
    assert today_hours.opens_at is None  # rejected - not saved as a bad pair
    assert today_hours.closes_at is None
    assert other_hours.opens_at == '09:00'  # the other day in the SAME submit still saves
    assert other_hours.closes_at == '18:00'


def test_update_business_hours_accepts_midnight_crossing(client, db):
    # opens_at > closes_at is a legitimate overnight schedule - must never be rejected.
    _register_owner(client)
    today = _today_weekday()

    resp = client.post('/admin/business-hours', data={
        f'opens_{today}': '18:00', f'closes_{today}': '02:00',
    })

    assert resp.status_code == 302
    hours = BusinessHours.query.filter_by(day_of_week=today).first()
    assert hours.opens_at == '18:00'
    assert hours.closes_at == '02:00'


def test_update_business_hours_accepts_normal_range(client, db):
    _register_owner(client)
    today = _today_weekday()

    resp = client.post('/admin/business-hours', data={
        f'opens_{today}': '18:00', f'closes_{today}': '23:00',
    })

    assert resp.status_code == 302
    hours = BusinessHours.query.filter_by(day_of_week=today).first()
    assert hours.opens_at == '18:00'
    assert hours.closes_at == '23:00'
