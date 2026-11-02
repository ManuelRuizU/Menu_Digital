"""Teaser banners: the countdown to an event day (Santiago's date, on the server), the
"Recuérdamelo" calendar file, the panel's event date, and the friendly "not yet" coupon."""
from datetime import date, datetime, timedelta, timezone

import pytest

import app.main.routes as main_routes
from app.catalog.banners import validate_banner
from app import create_app
from app.extensions import db as _db
from app.models import BUSINESS_TZ, BusinessHours, HeroBanner
from app.storefront import _ics_fold, banner_ics, countdown_label, reminder_alarm_utc


def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _banner(db, **fields):
    defaults = dict(desktop_image='banner_x_desktop.jpg', is_active=True, position=0)
    defaults.update(fields)
    banner = HeroBanner(**defaults)
    db.session.add(banner)
    db.session.commit()
    return banner


def _today():
    return datetime.now(BUSINESS_TZ).date()


def _freeze_utc(monkeypatch, moment):
    """Pins app.main.routes' "now" to a naive-UTC moment, whatever timezone it's asked in."""
    real_datetime = datetime

    class FixedNow(real_datetime):
        @classmethod
        def now(cls, tz=None):
            utc = moment.replace(tzinfo=timezone.utc)
            return utc.astimezone(tz) if tz else utc.replace(tzinfo=None)

    monkeypatch.setattr(main_routes, 'datetime', FixedNow)


def _values(**overrides):
    values = {'title': 'Cyber', 'text': '', 'button_label': '', 'target_type': 'none',
              'target_product_id': None, 'target_category_id': None, 'valid_from': '', 'valid_until': '',
              'event_date': '', 'show_reminder': False, 'is_active': True}
    values.update(overrides)
    return values


# --- Countdown -------------------------------------------------------------------------

def test_countdown_label_by_days_left():
    event = date(2026, 11, 11)
    assert countdown_label(event, date(2026, 11, 2)) == 'Faltan 9 días'
    assert countdown_label(event, date(2026, 11, 9)) == 'Faltan 2 días'
    assert countdown_label(event, date(2026, 11, 10)) == '¡Es mañana!'
    assert countdown_label(event, date(2026, 11, 11)) == '¡Es hoy!'
    assert countdown_label(event, date(2026, 11, 12)) is None
    assert countdown_label(None, date(2026, 11, 2)) is None


def test_countdown_turns_at_midnight_in_santiago_not_utc(client, db, monkeypatch):
    # Santiago is UTC-3 in November: 23:59 on the 10th there is 02:59 on the 11th in UTC.
    _banner(db, title='Cyber 11.11', event_date=date(2026, 11, 11))
    _freeze_utc(monkeypatch, datetime(2026, 11, 11, 2, 59))
    html = client.get('/').get_data(as_text=True)
    assert '<span class="hero-countdown">¡Es mañana!</span>' in html
    _freeze_utc(monkeypatch, datetime(2026, 11, 11, 3, 0))
    html = client.get('/').get_data(as_text=True)
    assert '<span class="hero-countdown">¡Es hoy!</span>' in html
    # And it's gone the day after, while the banner itself still shows.
    _freeze_utc(monkeypatch, datetime(2026, 11, 12, 3, 0))
    html = client.get('/').get_data(as_text=True)
    assert 'hero-countdown' not in html and 'Cyber 11.11' in html


def test_image_only_banner_still_shows_its_countdown(client, db):
    _banner(db, event_date=_today() + timedelta(days=5))
    html = client.get('/').get_data(as_text=True)
    assert '<span class="hero-countdown">Faltan 5 días</span>' in html
    assert 'hero-title' not in html


def test_banner_without_event_looks_as_before(client, db):
    _banner(db, title='Normal')
    html = client.get('/').get_data(as_text=True)
    assert 'hero-countdown' not in html and 'Recuérdamelo' not in html


# --- "Recuérdamelo" --------------------------------------------------------------------

def test_reminder_button_only_with_the_option_and_an_event_ahead(client, db):
    with_reminder = _banner(db, title='Con', event_date=_today() + timedelta(days=3), show_reminder=True)
    _banner(db, title='Sin', event_date=_today() + timedelta(days=3), position=1)
    html = client.get('/').get_data(as_text=True)
    assert html.count('Recuérdamelo') == 1
    assert f'href="/recordatorio/{with_reminder.id}.ics" download' in html


def test_reminder_ics_is_an_all_day_event_with_the_menu_link(client, db):
    _register_owner(client)
    event = _today() + timedelta(days=9)
    banner = _banner(db, title='Cyber 11.11', text='Hasta 30%, en toda la carta; solo ese día',
                     event_date=event, show_reminder=True)
    response = client.get(f'/recordatorio/{banner.id}.ics')
    assert response.status_code == 200
    assert response.mimetype == 'text/calendar'
    assert response.headers['Content-Disposition'] == f'attachment; filename="recordatorio-{event.isoformat()}.ics"'
    body = response.get_data(as_text=True)
    assert body.startswith('BEGIN:VCALENDAR\r\n') and body.endswith('END:VCALENDAR\r\n')
    assert '\nBEGIN:' in body and '\r\n' in body and '\n' not in body.replace('\r\n', '')
    unfolded = body.replace('\r\n ', '')
    assert f'DTSTART;VALUE=DATE:{event:%Y%m%d}\r\n' in unfolded
    assert f'DTEND;VALUE=DATE:{event + timedelta(days=1):%Y%m%d}\r\n' in unfolded
    assert f'UID:banner-{banner.id}-{event:%Y%m%d}@localhost\r\n' in unfolded
    assert 'SUMMARY:Cyber 11.11\r\n' in unfolded
    assert ('DESCRIPTION:Hasta 30%\\, en toda la carta\\; solo ese día\\n\\nVer la carta: http://localhost/\r\n'
            in unfolded)
    assert 'URL:http://localhost/\r\n' in unfolded
    # No business hours configured: the alert is at 10:00 Santiago that day.
    assert f'TRIGGER;VALUE=DATE-TIME:{reminder_alarm_utc(event, None):%Y%m%dT%H%M%SZ}\r\n' in unfolded


def test_reminder_without_title_uses_the_business_name(app, db):
    banner = HeroBanner(id=7, desktop_image='x.jpg', event_date=date(2026, 11, 11))
    body = banner_ics(banner, 'Lourdes Sushi', 'https://menu.cl/', 'menu.cl',
                      datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc))
    assert 'SUMMARY:Lourdes Sushi\r\n' in body
    assert 'DTSTAMP:20261102T150000Z\r\n' in body
    assert 'DESCRIPTION:Ver la carta: https://menu.cl/\r\n' in body


def test_alarm_is_30_minutes_before_opening_in_santiago_or_10_without_hours():
    # November: Santiago is UTC-3. June: UTC-4 - the same local time is a different UTC.
    assert reminder_alarm_utc(date(2026, 11, 11), '18:00') == datetime(2026, 11, 11, 20, 30, tzinfo=timezone.utc)
    assert reminder_alarm_utc(date(2026, 6, 15), '12:00') == datetime(2026, 6, 15, 15, 30, tzinfo=timezone.utc)
    assert reminder_alarm_utc(date(2026, 11, 11), None) == datetime(2026, 11, 11, 13, 0, tzinfo=timezone.utc)
    # Opening just after midnight: the alert falls the evening before.
    assert reminder_alarm_utc(date(2026, 11, 11), '00:15') == datetime(2026, 11, 11, 2, 45, tzinfo=timezone.utc)


def test_reminder_alarm_uses_the_opening_hour_of_the_event_weekday(client, db):
    event = _today() + timedelta(days=3)
    db.session.add(BusinessHours(day_of_week=event.weekday(), opens_at='18:00', closes_at='23:00'))
    other = (event.weekday() + 1) % 7
    db.session.add(BusinessHours(day_of_week=other, opens_at='11:00', closes_at='15:00'))
    db.session.commit()
    banner = _banner(db, title='Cyber', event_date=event, show_reminder=True)
    body = client.get(f'/recordatorio/{banner.id}.ics').get_data(as_text=True)
    assert f'TRIGGER;VALUE=DATE-TIME:{reminder_alarm_utc(event, "18:00"):%Y%m%dT%H%M%SZ}\r\n' in body

    # Closed on the event's weekday (hours set for other days only): 10:00.
    BusinessHours.query.filter_by(day_of_week=event.weekday()).delete()
    db.session.commit()
    body = client.get(f'/recordatorio/{banner.id}.ics').get_data(as_text=True)
    assert f'TRIGGER;VALUE=DATE-TIME:{reminder_alarm_utc(event, None):%Y%m%dT%H%M%SZ}\r\n' in body


@pytest.mark.parametrize('behind_proxy, scheme', [(True, 'https'), (False, 'http')])
def test_menu_link_follows_x_forwarded_proto_only_behind_proxy(tmp_path, behind_proxy, scheme):
    application = create_app({
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "proxy.db"}', 'TESTING': True,
        'WTF_CSRF_ENABLED': False, 'SESSION_COOKIE_SECURE': False, 'SECRET_KEY': 'test',
        'BEHIND_PROXY': behind_proxy,
    })
    with application.app_context():
        banner = HeroBanner(desktop_image='x.jpg', title='Cyber', is_active=True, position=0,
                            event_date=_today() + timedelta(days=3), show_reminder=True)
        _db.session.add(banner)
        _db.session.commit()
        banner_id = banner.id
    body = application.test_client().get(
        f'/recordatorio/{banner_id}.ics',
        headers={'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'mitienda.cl', 'Host': '127.0.0.1:8000'},
    ).get_data(as_text=True).replace('\r\n ', '')
    host = 'mitienda.cl' if behind_proxy else '127.0.0.1:8000'
    assert f'URL:{scheme}://{host}/\r\n' in body
    assert f'Ver la carta: {scheme}://{host}/' in body


def test_ics_lines_fold_at_75_octets_without_splitting_characters():
    line = 'DESCRIPTION:' + 'ñ' * 80
    folded = _ics_fold(line)
    for part in folded.split('\r\n'):
        assert len(part.encode('utf-8')) <= 75
    assert folded.replace('\r\n ', '') == line


@pytest.mark.parametrize('fields', [
    {'show_reminder': False},
    {'is_active': False},
    {'event_date_days': -1},
    {'valid_until_days': -1},
])
def test_reminder_ics_is_404_when_the_button_would_not_show(client, db, fields):
    today = _today()
    event_days = fields.pop('event_date_days', 3)
    until_days = fields.pop('valid_until_days', None)
    values = dict(title='X', event_date=today + timedelta(days=event_days), show_reminder=True)
    if until_days is not None:
        values['valid_until'] = today + timedelta(days=until_days)
    values.update(fields)
    banner = _banner(db, **values)
    assert client.get(f'/recordatorio/{banner.id}.ics').status_code == 404


def test_reminder_ics_unknown_banner_is_404(client, db):
    assert client.get('/recordatorio/999.ics').status_code == 404


# --- Panel -----------------------------------------------------------------------------

def test_event_date_may_be_inside_or_after_the_banner_dates_never_before(db):
    today = date(2026, 11, 2)
    fields, error = validate_banner(_values(valid_from='2026-11-05', valid_until='2026-11-08',
                                            event_date='2026-11-11'), today=today)
    assert error is None and fields['event_date'] == date(2026, 11, 11)
    fields, error = validate_banner(_values(valid_from='2026-11-05', event_date='2026-11-05'), today=today)
    assert error is None
    _, error = validate_banner(_values(valid_from='2026-11-05', event_date='2026-11-04'), today=today)
    assert error == 'La fecha del evento no puede ser anterior a «Mostrar desde».'


def test_a_past_event_date_is_refused_only_when_typed_now(db):
    today = date(2026, 11, 12)
    _, error = validate_banner(_values(event_date='2026-11-11'), today=today)
    assert error == 'La fecha del evento ya pasó.'
    saved = _banner(db, title='Viejo', event_date=date(2026, 11, 11))
    fields, error = validate_banner(_values(event_date='2026-11-11', title='Viejo editado'), banner=saved, today=today)
    assert error is None and fields['title'] == 'Viejo editado'


def test_reminder_needs_an_event_date_and_bad_dates_are_refused(db):
    _, error = validate_banner(_values(show_reminder=True))
    assert error == 'El botón «Recuérdamelo» necesita una fecha del evento.'
    _, error = validate_banner(_values(event_date='11/11/2026'))
    assert error == 'Una de las fechas no es válida.'


def test_panel_saves_event_and_warns_when_the_banner_has_no_end(client, db, tmp_path, app):
    from io import BytesIO
    from PIL import Image
    app.config['BANNER_UPLOAD_DIR'] = str(tmp_path)
    _register_owner(client)
    image = BytesIO()
    Image.new('RGB', (1200, 400), (200, 80, 40)).save(image, format='PNG')
    image.seek(0)
    event = (_today() + timedelta(days=9)).isoformat()
    response = client.post('/admin/banners/new', data={
        'title': 'Cyber', 'text': '', 'button_label': '', 'target_type': 'none', 'valid_from': '',
        'valid_until': '', 'event_date': event, 'show_reminder': 'on', 'is_active': 'on',
        'desktop_image': (image, 'b.png')}, content_type='multipart/form-data', follow_redirects=True)
    html = response.get_data(as_text=True)
    banner = HeroBanner.query.one()
    assert banner.event_date.isoformat() == event and banner.show_reminder
    assert 'seguirá visible sin la cuenta regresiva' in html
    assert f'Evento: {banner.event_date.strftime("%d/%m")} (con «Recuérdamelo»)' in html

    form = client.get(f'/admin/banners/{banner.id}/edit').get_data(as_text=True)
    assert f'name="event_date" value="{event}"' in form
    assert 'Para anunciar un evento: muestra la cuenta regresiva' in form
