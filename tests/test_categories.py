from app.models import Category, Product, Subcategory


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _create_subcategory(db, name='Hand rolls', description=None):
    category = Category(name='Sushi')
    db.session.add(category)
    db.session.flush()
    subcategory = Subcategory(name=name, category_id=category.id, description=description)
    db.session.add(subcategory)
    db.session.commit()
    return subcategory


# --- update_subcategory: only the description ---

def test_update_subcategory_saves_description(client, db):
    _register_owner(client)
    sub = _create_subcategory(db)

    resp = client.post(f'/admin/subcategories/{sub.id}/edit',
                       data={'description': '  pollo, camarón, salmón  '}, follow_redirects=True)

    db.session.refresh(sub)
    assert sub.description == 'pollo, camarón, salmón'  # trimmed
    assert 'Descripción guardada'.encode() in resp.data


def test_update_subcategory_edits_existing_description(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, description='vieja')

    client.post(f'/admin/subcategories/{sub.id}/edit', data={'description': 'nueva'})

    db.session.refresh(sub)
    assert sub.description == 'nueva'


def test_update_subcategory_empty_removes_description(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, description='algo')

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data={'description': '   '}, follow_redirects=True)

    db.session.refresh(sub)
    assert sub.description is None
    assert 'Descripción quitada'.encode() in resp.data


def test_update_subcategory_never_touches_the_name(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')

    client.post(f'/admin/subcategories/{sub.id}/edit', data={'description': 'x', 'name': 'Otro nombre'})

    db.session.refresh(sub)
    assert sub.name == 'Hand rolls'


def test_update_subcategory_rejects_more_than_200_chars(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, description='original')

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data={'description': 'x' * 201},
                       follow_redirects=True)

    db.session.refresh(sub)
    assert sub.description == 'original'
    assert 'hasta 200 caracteres'.encode() in resp.data


def test_update_subcategory_accepts_exactly_200_chars(client, db):
    _register_owner(client)
    sub = _create_subcategory(db)

    client.post(f'/admin/subcategories/{sub.id}/edit', data={'description': 'x' * 200})

    db.session.refresh(sub)
    assert sub.description == 'x' * 200


def test_update_subcategory_requires_login(client, db):
    sub = _create_subcategory(db)

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data={'description': 'hack'})

    assert resp.status_code in (302, 401, 403)
    db.session.refresh(sub)
    assert sub.description is None


def test_update_subcategory_unknown_id_is_404(client, db):
    _register_owner(client)

    resp = client.post('/admin/subcategories/9999/edit', data={'description': 'x'})

    assert resp.status_code == 404


# --- panel listing ---

def test_categories_panel_shows_description_and_edit_toggle(client, db):
    _register_owner(client)
    _create_subcategory(db, name='Hand rolls', description='pollo, camarón, salmón')
    rolls = Subcategory(name='Rolls', category_id=Category.query.one().id)
    db.session.add(rolls)
    db.session.commit()

    html = client.get('/admin/categories').data.decode()

    assert '<small class="muted">pollo, camarón, salmón</small>' in html
    assert 'Editar descripción' in html   # Hand rolls has one
    assert 'Agregar descripción' in html  # Rolls doesn't


def test_categories_panel_escapes_description(client, db):
    _register_owner(client)
    _create_subcategory(db, description='<script>alert(1)</script>')

    html = client.get('/admin/categories').data.decode()

    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html


# --- /api/products carries it to the public menu ---

def test_products_api_includes_subcategory_description(client, db):
    with_desc = _create_subcategory(db, name='Hand rolls', description='pollo, camarón')
    category = Category.query.one()
    without_desc = Subcategory(name='Rolls', category_id=category.id)
    db.session.add(without_desc)
    db.session.flush()
    db.session.add_all([
        Product(name='Hand pollo', description='T', price=1, category_id=category.id, subcategory_id=with_desc.id),
        Product(name='Roll simple', description='T', price=1, category_id=category.id, subcategory_id=without_desc.id),
        Product(name='Suelto', description='T', price=1, category_id=category.id),
    ])
    db.session.commit()

    payload = {item['name']: item for item in client.get('/api/products').get_json()}

    assert payload['Hand pollo']['subcategoryDescription'] == 'pollo, camarón'
    assert payload['Roll simple']['subcategoryDescription'] is None  # existing subcategory, no description
    assert payload['Suelto']['subcategoryDescription'] is None       # no subcategory at all
