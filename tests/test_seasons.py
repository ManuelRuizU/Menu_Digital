"""Seasonal decorations: which celebration shows on a Santiago day, the catalog's computed
dates, overlaps, the owner's own celebrations (emojis and colors checked on the server),
the master switch, the owner-only preview, and the menu page loading nothing extra when
no celebration is on."""
from datetime import date, datetime, timezone

import pytest

import app.main.routes as main_routes
from app.models import Celebration, User
from app.seasons import (active_celebration, easter_sunday, is_single_emoji, look, nth_sunday, overlap_warnings,
                         parse_day_month, validate_custom)


def _preset(db, key, **fields):
    values = dict(kind='preset', motif=key, is_active=True, ambient=True, burst=True)
    values.update(fields)
    row = Celebration(**values)
    db.session.add(row)
    db.session.commit()
    return row


def _custom(db, name, start, end, **fields):
    values = dict(kind='custom', motif='personal', name=name, start_date=start, end_date=end, is_active=True,
                  emojis='🎂 🎉', accent='#123456', ambient=True, burst=True)
    values.update(fields)
    row = Celebration(**values)
    db.session.add(row)
    db.session.commit()
    return row


def _shown(today):
    found = active_celebration(today)
    return found[0].motif if found and found[0].kind == 'preset' else (found[0].name if found else None)


def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _freeze_utc(monkeypatch, moment):
    real_datetime = datetime

    class FixedNow(real_datetime):
        @classmethod
        def now(cls, tz=None):
            utc = moment.replace(tzinfo=timezone.utc)
            return utc.astimezone(tz) if tz else utc.replace(tzinfo=None)

    monkeypatch.setattr(main_routes, 'datetime', FixedNow)


def _switch_on(db):
    owner = User.query.filter_by(is_owner=True).first()
    owner.seasonal_decor_enabled = True
    db.session.commit()


# --- Computed dates ----------------------------------------------------------------------

@pytest.mark.parametrize('year, expected', [
    (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)),
    (2038, date(2038, 4, 25)), (2008, date(2008, 3, 23)), (2285, date(2285, 3, 22)),
])
def test_easter_sunday(year, expected):
    assert easter_sunday(year) == expected


def test_chilean_mothers_fathers_and_childrens_days_2026():
    assert nth_sunday(2026, 5, 2) == date(2026, 5, 10)
    assert nth_sunday(2026, 6, 3) == date(2026, 6, 21)
    assert nth_sunday(2026, 8, 2) == date(2026, 8, 9)


def test_computed_celebrations_run_the_week_up_to_their_sunday(db):
    _preset(db, 'pascua')
    _preset(db, 'dia_madre')
    assert _shown(date(2026, 3, 29)) is None
    assert _shown(date(2026, 3, 30)) == 'pascua'   # Monday
    assert _shown(date(2026, 4, 5)) == 'pascua'    # Easter Sunday
    assert _shown(date(2026, 4, 6)) is None
    assert _shown(date(2026, 5, 4)) == 'dia_madre'
    assert _shown(date(2026, 5, 10)) == 'dia_madre'
    assert _shown(date(2026, 5, 11)) is None


# --- Activation by date ------------------------------------------------------------------

def test_nothing_shows_by_default(db):
    assert active_celebration(date(2026, 12, 20)) is None


def test_navidad_then_ano_nuevo_across_the_new_year(db):
    _preset(db, 'navidad')
    _preset(db, 'ano_nuevo')
    assert _shown(date(2026, 11, 30)) is None
    assert _shown(date(2026, 12, 1)) == 'navidad'
    assert _shown(date(2026, 12, 25)) == 'navidad'
    assert _shown(date(2026, 12, 26)) == 'ano_nuevo'
    assert _shown(date(2027, 1, 1)) == 'ano_nuevo'   # started last year, still on
    assert _shown(date(2027, 1, 2)) is None


def test_owner_edited_dates_and_a_switched_off_one(db):
    _preset(db, 'halloween', start_md='10-20', end_md='11-01')
    _preset(db, 'navidad', is_active=False)
    assert _shown(date(2026, 10, 20)) == 'halloween'
    assert _shown(date(2026, 11, 1)) == 'halloween'
    assert _shown(date(2026, 12, 10)) is None


def test_menu_turns_at_midnight_in_santiago_not_utc(client, db, monkeypatch):
    _register_owner(client)
    _switch_on(db)
    _preset(db, 'navidad')
    _preset(db, 'ano_nuevo')
    client.get('/logout')
    # Santiago is UTC-3 in December: 23:59 on the 25th there is 02:59 on the 26th in UTC.
    _freeze_utc(monkeypatch, datetime(2026, 12, 26, 2, 59))
    assert '"name": "Navidad"' in client.get('/').get_data(as_text=True)
    _freeze_utc(monkeypatch, datetime(2026, 12, 26, 3, 0))
    assert '"name": "A\\u00f1o Nuevo"' in client.get('/').get_data(as_text=True)


# --- Overlaps ----------------------------------------------------------------------------

def test_overlap_shows_the_shortest_and_the_panel_warns(db):
    _preset(db, 'navidad')
    _custom(db, 'Aniversario', date(2026, 12, 10), date(2026, 12, 15))
    assert _shown(date(2026, 12, 9)) == 'navidad'
    assert _shown(date(2026, 12, 12)) == 'Aniversario'
    assert _shown(date(2026, 12, 16)) == 'navidad'
    assert overlap_warnings(date(2026, 11, 2)) == [
        'Navidad y «Aniversario» se solapan del 10/12 al 15/12; se mostrará «Aniversario».']


def test_overlap_tie_goes_to_the_owners_own(db):
    _preset(db, 'halloween')
    _custom(db, 'Mi Halloween', date(2026, 10, 25), date(2026, 10, 31))
    assert _shown(date(2026, 10, 28)) == 'Mi Halloween'


# --- The owner's own: validation -----------------------------------------------------------

@pytest.mark.parametrize('value', ['❄️', '🏳️‍🌈', '🇨🇱', '🧙‍♀️', '👍🏽', '❤️', '🎄', '1️⃣'])
def test_real_emojis_are_accepted(value):
    assert is_single_emoji(value)


@pytest.mark.parametrize('value', ['a', 'ñ', '<b>', '<script>', '😀😀', ' 🎄', 'x😀', '', '1', '&', '🎄🎄🎄'])
def test_text_html_and_several_emojis_are_refused(value):
    assert not is_single_emoji(value)


def _custom_form(**overrides):
    form = {'name': 'Aniversario', 'start_date': '2026-12-10', 'end_date': '2026-12-15', 'motif': 'personal',
            'emoji_1': '🎂', 'emoji_2': '🎉', 'emoji_3': '', 'accent': '#C62828', 'ambient': 'on', 'burst': 'on',
            'is_active': 'on'}
    form.update(overrides)
    return form


def test_custom_validation(db):
    fields, error = validate_custom(_custom_form(), date(2026, 11, 2))
    assert error is None
    assert fields['emojis'] == '🎂 🎉' and fields['accent'] == '#c62828'
    cases = {
        'Cada casilla debe tener un solo emoji (sin letras ni otros signos).': {'emoji_2': '<b>hola</b>'},
        'Escribe al menos un emoji.': {'emoji_1': '', 'emoji_2': ''},
        'Elige un color de acento válido (ej. #c62828).': {'accent': 'red; background:url(x)'},
        'La fecha «desde» no puede ser posterior a la fecha «hasta».': {'start_date': '2026-12-20'},
        'Escribe el nombre de la celebración.': {'name': '  '},
        'Elige un motivo.': {'motif': 'otro'},
    }
    for message, overrides in cases.items():
        assert validate_custom(_custom_form(**overrides), date(2026, 11, 2)) == (None, message)
    # A catalog motif needs no emojis or color.
    fields, error = validate_custom(_custom_form(motif='navidad', emoji_1='', emoji_2='', accent='x'), date(2026, 11, 2))
    assert error is None and fields['emojis'] is None


def test_day_month_parsing():
    assert parse_day_month('1/12') == '12-01'
    assert parse_day_month('29/2') == '02-29'
    assert parse_day_month('31/2') is None
    assert parse_day_month('12-01') is None


def test_personal_look_uses_its_emojis_and_color(db):
    row = _custom(db, 'Aniversario', date(2026, 12, 10), date(2026, 12, 15))
    seen = look(row)
    assert seen['particles'] == ['🎂', '🎉'] and seen['burst'] == ['🎂', '🎉']
    assert seen['accent'] == '#123456' and seen['band'] == '#123456'
    assert seen['crossing'] == '🎂🎉'


# --- The menu page -----------------------------------------------------------------------

def test_menu_loads_nothing_seasonal_without_a_celebration(client, db):
    _register_owner(client)
    _preset(db, 'navidad')  # on, but the master switch is off
    client.get('/logout')
    html = client.get('/').get_data(as_text=True)
    assert 'seasonal.js' not in html and 'seasonal.css' not in html and 'season-data' not in html


def test_menu_shows_todays_celebration_when_switched_on(client, db, monkeypatch):
    _register_owner(client)
    _switch_on(db)
    _preset(db, 'navidad', burst=False)
    client.get('/logout')
    _freeze_utc(monkeypatch, datetime(2026, 12, 20, 15, 0))
    html = client.get('/').get_data(as_text=True)
    assert 'seasonal.js' in html and 'seasonal.css' in html
    assert '--season-accent: #c62828;' in html
    assert '"burstOn": false' in html and '"ambient": true' in html
    assert 'season-preview-band' not in html


def test_custom_emojis_reach_the_page_escaped(client, db, monkeypatch):
    _register_owner(client)
    _switch_on(db)
    _custom(db, '</script><b>x', date(2026, 12, 10), date(2026, 12, 15))
    client.get('/logout')
    _freeze_utc(monkeypatch, datetime(2026, 12, 12, 15, 0))
    html = client.get('/').get_data(as_text=True)
    assert '</script><b>x' not in html


# --- Preview -----------------------------------------------------------------------------

def test_owner_preview_shows_any_celebration_with_a_band(client, db):
    _register_owner(client)  # logged in as the owner
    html = client.get('/?temporada=halloween').get_data(as_text=True)
    assert 'Vista previa: Halloween' in html and '"preview": true' in html
    assert '--season-accent: #ff7518;' in html
    # Even with the master switch off and nothing saved - and nothing gets saved.
    assert Celebration.query.count() == 0


def test_owner_preview_of_an_own_celebration(client, db):
    _register_owner(client)
    row = _custom(db, 'Aniversario', date(2027, 3, 1), date(2027, 3, 3), is_active=False)
    html = client.get(f'/?temporada=c{row.id}').get_data(as_text=True)
    assert 'Vista previa: Aniversario' in html


@pytest.mark.parametrize('value', ['halloween', 'c1', 'navidad'])
def test_customers_cannot_preview(client, db, value):
    _register_owner(client)
    _custom(db, 'Aniversario', date(2027, 3, 1), date(2027, 3, 3))
    client.get('/logout')
    html = client.get(f'/?temporada={value}').get_data(as_text=True)
    assert 'Vista previa' not in html and 'seasonal.js' not in html


@pytest.mark.parametrize('value', ['<script>', 'c', 'c99', 'x' * 200])
def test_unknown_preview_values_are_ignored(client, db, value):
    _register_owner(client)
    response = client.get('/', query_string={'temporada': value})
    assert response.status_code == 200
    assert 'Vista previa' not in response.get_data(as_text=True)


# --- Panel -------------------------------------------------------------------------------

def test_panel_switch_presets_and_custom_crud(client, db):
    _register_owner(client)
    page = client.get('/admin/temporada').get_data(as_text=True)
    assert 'Adornos de temporada' in page and 'Apagados' in page
    assert page.count('Ver cómo se ve') == 11

    client.post('/admin/temporada/interruptor', data={'enabled': 'on'})
    assert User.query.filter_by(is_owner=True).first().seasonal_decor_enabled

    client.post('/admin/temporada/catalogo/navidad',
                data={'is_active': 'on', 'start_md': '5/12', 'end_md': '25/12', 'ambient': 'on'})
    row = Celebration.query.filter_by(motif='navidad').one()
    assert (row.is_active, row.start_md, row.end_md, row.ambient, row.burst) == (True, '12-05', '12-25', True, False)

    response = client.post('/admin/temporada/catalogo/pascua', data={'is_active': 'on', 'days_before': '40'},
                           follow_redirects=True)
    assert 'Escribe cuántos días antes empieza (0 a 30).' in response.get_data(as_text=True)
    assert client.post('/admin/temporada/catalogo/inventada', data={}).status_code == 404

    client.post('/admin/temporada/nueva', data=_custom_form())
    custom = Celebration.query.filter_by(kind='custom').one()
    assert custom.emojis == '🎂 🎉'
    response = client.post(f'/admin/temporada/{custom.id}/editar', data=_custom_form(emoji_1='hola'))
    assert 'Cada casilla debe tener un solo emoji' in response.get_data(as_text=True)
    client.post(f'/admin/temporada/{custom.id}/borrar')
    assert Celebration.query.filter_by(kind='custom').count() == 0


def test_panel_is_owner_only(client, db):
    assert client.get('/admin/temporada').status_code in (302, 401, 403)
