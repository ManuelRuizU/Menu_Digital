from app.models import User


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


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
