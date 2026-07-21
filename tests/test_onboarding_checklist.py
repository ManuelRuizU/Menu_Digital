from app.models import BusinessHours, Category, Product, User


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _owner():
    return User.query.filter_by(is_owner=True).first()


def _complete_all_five_tasks(db):
    owner = _owner()
    owner.whatsapp_number = '56912345678'
    db.session.add(BusinessHours(day_of_week=0, opens_at='09:00', closes_at='18:00'))
    category = Category(name='Bebidas')
    db.session.add(category)
    db.session.commit()
    db.session.add(Product(name='Jugo', description='Test', price=1000, category_id=category.id,
                            is_active=True, image_filename='jugo.jpg'))
    db.session.commit()


def test_fresh_install_shows_all_five_tasks_pending(client, db):
    _register_owner(client)

    resp = client.get('/admin/dashboard')
    html = resp.data.decode()

    assert resp.status_code == 200
    assert '0 de 5 completadas' in html
    assert 'Configura tu horario de atención' in html
    assert 'Crea tu primera categoría' in html
    assert 'Agrega tu primer producto' in html
    assert 'Súbele una foto a un producto' in html
    assert 'Configura tu WhatsApp' in html


def test_two_tasks_done_shows_2_of_5(client, db):
    _register_owner(client)
    db.session.add(BusinessHours(day_of_week=0, opens_at='09:00', closes_at='18:00'))
    db.session.add(Category(name='Bebidas'))
    db.session.commit()

    resp = client.get('/admin/dashboard')
    html = resp.data.decode()

    assert '2 de 5 completadas' in html


def test_all_five_tasks_done_checklist_not_rendered(client, db):
    _register_owner(client)
    _complete_all_five_tasks(db)

    resp = client.get('/admin/dashboard')
    html = resp.data.decode()

    assert 'Primeros pasos' not in html
    assert 'completadas' not in html


def test_dismissed_checklist_not_rendered_even_with_tasks_pending(client, db):
    _register_owner(client)
    owner = _owner()
    owner.onboarding_checklist_dismissed = True
    db.session.commit()

    resp = client.get('/admin/dashboard')
    html = resp.data.decode()

    assert 'Primeros pasos' not in html
    assert 'completadas' not in html


def test_delivery_suggestion_does_not_count_toward_the_five(client, db):
    # All 5 real tasks done, no delivery zones configured - the checklist must still
    # disappear. A retiro-only business can never "complete" a delivery task, so it
    # must never block the checklist from going away.
    _register_owner(client)
    _complete_all_five_tasks(db)

    resp = client.get('/admin/dashboard')
    html = resp.data.decode()

    assert 'Primeros pasos' not in html
    assert '¿Haces despacho a domicilio?' not in html


def test_dismiss_route_persists_and_redirects_to_dashboard(client, db):
    _register_owner(client)

    resp = client.post('/admin/onboarding-checklist/dismiss')

    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/dashboard')
    owner = _owner()
    assert owner.onboarding_checklist_dismissed is True
