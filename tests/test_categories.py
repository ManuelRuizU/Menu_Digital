from html import unescape

from werkzeug.security import generate_password_hash

from app.models import Category, Order, Product, Subcategory, User


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


# --- helpers for editing ---

def _create_category(db, name):
    category = Category(name=name)
    db.session.add(category)
    db.session.commit()
    return category


def _create_product(db, category, subcategory=None, name='Hand roll pollo', price=2990):
    product = Product(name=name, description='T', price=price, category_id=category.id,
                      subcategory_id=subcategory.id if subcategory else None)
    db.session.add(product)
    db.session.commit()
    return product


def _sub_form(sub, **overrides):
    """The subcategory form as the browser sends it, with the current values."""
    data = {'name': sub.name, 'description': sub.description or '', 'category_id': str(sub.category_id)}
    data.update(overrides)
    return data


def _login_as(client, db, email, is_admin):
    user = User(username=email.split('@')[0], email=email, password_hash=generate_password_hash('secret123'),
                is_admin=is_admin, is_owner=False)
    db.session.add(user)
    db.session.commit()
    client.get('/logout')
    client.post('/login', data={'email': email, 'password': 'secret123'})


# --- editing a category ---

def test_rename_category_trims_and_redirects_with_flash(client, db):
    _register_owner(client)
    category = _create_category(db, 'Sushi')

    resp = client.post(f'/admin/categories/{category.id}/edit', data={'name': '  Sushi & rolls  '},
                       follow_redirects=True)

    db.session.refresh(category)
    assert category.name == 'Sushi & rolls'
    assert 'Categoría guardada' in unescape(resp.data.decode())
    assert resp.request.path == '/admin/categories'


def test_category_edit_form_shows_the_current_name(client, db):
    _register_owner(client)
    category = _create_category(db, 'Sushi')

    html = client.get(f'/admin/categories/{category.id}/edit').data.decode()

    assert 'value="Sushi"' in html


def test_rename_category_rejects_an_empty_name(client, db):
    _register_owner(client)
    category = _create_category(db, 'Sushi')

    resp = client.post(f'/admin/categories/{category.id}/edit', data={'name': '   '})

    assert 'El nombre de la categoría es obligatorio.' in unescape(resp.data.decode())
    db.session.refresh(category)
    assert category.name == 'Sushi'


def test_rename_category_rejects_a_duplicate_and_keeps_what_was_typed(client, db):
    _register_owner(client)
    _create_category(db, 'Bebidas')
    category = _create_category(db, 'Sushi')

    resp = client.post(f'/admin/categories/{category.id}/edit', data={'name': 'Bebidas'})

    html = unescape(resp.data.decode())
    assert 'Ya existe una categoría con ese nombre.' in html
    assert 'value="Bebidas"' in html
    db.session.refresh(category)
    assert category.name == 'Sushi'


def test_saving_a_category_with_its_own_name_is_not_a_duplicate(client, db):
    _register_owner(client)
    category = _create_category(db, 'Sushi')

    resp = client.post(f'/admin/categories/{category.id}/edit', data={'name': 'Sushi'}, follow_redirects=True)

    assert 'Categoría guardada' in unescape(resp.data.decode())


def test_edit_category_unknown_id_is_404(client, db):
    _register_owner(client)

    assert client.get('/admin/categories/9999/edit').status_code == 404
    assert client.post('/admin/categories/9999/edit', data={'name': 'x'}).status_code == 404


# --- editing a subcategory ---

def test_rename_subcategory_and_its_description(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls', description='vieja')

    resp = client.post(f'/admin/subcategories/{sub.id}/edit',
                       data=_sub_form(sub, name='  Handrolls  ', description='  pollo, camarón  '),
                       follow_redirects=True)

    db.session.refresh(sub)
    assert (sub.name, sub.description) == ('Handrolls', 'pollo, camarón')  # trimmed
    assert 'Subcategoría guardada' in unescape(resp.data.decode())


def test_subcategory_empty_description_removes_it(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, description='algo')

    client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, description='   '))

    db.session.refresh(sub)
    assert sub.description is None


def test_subcategory_description_length_limit(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, description='original')

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, description='x' * 201))
    assert 'hasta 200 caracteres' in unescape(resp.data.decode())
    db.session.refresh(sub)
    assert sub.description == 'original'

    client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, description='x' * 200))
    db.session.refresh(sub)
    assert sub.description == 'x' * 200


def test_rename_subcategory_rejects_an_empty_name(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, name='  '))

    assert 'Completa el nombre y la categoría' in unescape(resp.data.decode())
    db.session.refresh(sub)
    assert sub.name == 'Hand rolls'


def test_rename_subcategory_rejects_a_duplicate_in_the_same_category(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')
    db.session.add(Subcategory(name='Rolls', category_id=sub.category_id))
    db.session.commit()

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, name='Rolls'))

    assert 'Ya existe una subcategoría con ese nombre en Sushi.' in unescape(resp.data.decode())
    db.session.refresh(sub)
    assert sub.name == 'Hand rolls'


def test_the_same_subcategory_name_is_fine_in_another_category(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')
    postres = _create_category(db, 'Postres')
    db.session.add(Subcategory(name='Frios', category_id=postres.id))
    db.session.commit()

    client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, name='Frios'))

    db.session.refresh(sub)
    assert sub.name == 'Frios'


def test_moving_into_a_category_that_has_that_name_is_a_duplicate(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Frios')
    postres = _create_category(db, 'Postres')
    db.session.add(Subcategory(name='Frios', category_id=postres.id))
    db.session.commit()
    sushi_id = sub.category_id

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, category_id=str(postres.id)))

    assert 'Ya existe una subcategoría con ese nombre en Postres.' in unescape(resp.data.decode())
    db.session.refresh(sub)
    assert sub.category_id == sushi_id


def test_moving_a_subcategory_moves_its_products_in_the_same_save(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')
    sushi = Category.query.one()
    other_sub = Subcategory(name='Rolls', category_id=sushi.id)
    db.session.add(other_sub)
    db.session.commit()
    moved = [_create_product(db, sushi, sub, name=n) for n in ('Hand pollo', 'Hand salmón')]
    stays = _create_product(db, sushi, other_sub, name='Roll simple')
    no_sub = _create_product(db, sushi, name='Gyozas')
    entradas = _create_category(db, 'Entradas')

    form_html = client.get(f'/admin/subcategories/{sub.id}/edit').data.decode()
    assert 'Tiene 2 productos.' in ' '.join(form_html.split())

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, category_id=str(entradas.id)),
                       follow_redirects=True)

    assert 'Subcategoría guardada y movida a Entradas, con 2 productos.' in unescape(resp.data.decode())
    db.session.expire_all()
    assert Subcategory.query.get(sub.id).category_id == entradas.id
    assert {Product.query.get(p.id).category_id for p in moved} == {entradas.id}
    assert Product.query.get(stays.id).category_id == sushi.id
    assert Product.query.get(no_sub.id).category_id == sushi.id
    # The public menu groups them under the new category.
    payload = {item['name']: item for item in client.get('/api/products').get_json()}
    assert (payload['Hand pollo']['category'], payload['Hand pollo']['subcategory']) == ('Entradas', 'Hand rolls')


def test_a_failed_move_leaves_the_products_where_they_were(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Frios')
    sushi = Category.query.one()
    product = _create_product(db, sushi, sub)
    postres = _create_category(db, 'Postres')
    db.session.add(Subcategory(name='Frios', category_id=postres.id))
    db.session.commit()

    client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, category_id=str(postres.id)))

    db.session.expire_all()
    assert Product.query.get(product.id).category_id == sushi.id


def test_edit_subcategory_rejects_an_unknown_category(client, db):
    _register_owner(client)
    sub = _create_subcategory(db)

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, category_id='9999'))

    assert 'Completa el nombre y la categoría' in unescape(resp.data.decode())


def test_edit_subcategory_unknown_id_is_404(client, db):
    _register_owner(client)

    assert client.get('/admin/subcategories/9999/edit').status_code == 404


# --- duplicates ignore case and surrounding spaces, on create and edit ---

def test_create_category_rejects_a_duplicate_in_other_case_or_spacing(client, db):
    _register_owner(client)
    _create_category(db, 'Bebidas')
    _create_category(db, 'Fríos')

    for typed in ('bebidas', '  BEBIDAS  ', 'FRÍOS'):
        resp = client.post('/admin/categories/new', data={'name': typed}, follow_redirects=True)
        assert 'Ya existe una categoría con ese nombre.' in unescape(resp.data.decode()), typed
    assert Category.query.count() == 2


def test_edit_category_rejects_a_duplicate_in_other_case_or_spacing(client, db):
    _register_owner(client)
    _create_category(db, 'Bebidas')
    category = _create_category(db, 'Sushi')

    resp = client.post(f'/admin/categories/{category.id}/edit', data={'name': ' bEBIDAS '})

    assert 'Ya existe una categoría con ese nombre.' in unescape(resp.data.decode())
    db.session.refresh(category)
    assert category.name == 'Sushi'


def test_a_category_can_change_only_the_case_of_its_own_name(client, db):
    _register_owner(client)
    category = _create_category(db, 'sushi')

    client.post(f'/admin/categories/{category.id}/edit', data={'name': 'Sushi'})

    db.session.refresh(category)
    assert category.name == 'Sushi'


def test_create_subcategory_rejects_a_duplicate_in_other_case_in_its_category_only(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')
    postres = _create_category(db, 'Postres')

    resp = client.post('/admin/subcategories/new', data={'name': '  HAND ROLLS ', 'category_id': sub.category_id},
                       follow_redirects=True)
    assert 'Ya existe una subcategoría con ese nombre en esta categoría.' in unescape(resp.data.decode())

    client.post('/admin/subcategories/new', data={'name': 'hand rolls', 'category_id': postres.id})
    assert Subcategory.query.filter_by(category_id=postres.id).one().name == 'hand rolls'
    assert Subcategory.query.count() == 2


def test_edit_subcategory_rejects_a_duplicate_in_other_case_including_when_moving(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')
    db.session.add(Subcategory(name='Fríos', category_id=sub.category_id))
    postres = _create_category(db, 'Postres')
    db.session.add(Subcategory(name='Tortas', category_id=postres.id))
    db.session.commit()

    resp = client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, name='FRÍOS '))
    assert 'Ya existe una subcategoría con ese nombre en Sushi.' in unescape(resp.data.decode())

    resp = client.post(f'/admin/subcategories/{sub.id}/edit',
                       data=_sub_form(sub, name='tortas', category_id=str(postres.id)))
    assert 'Ya existe una subcategoría con ese nombre en Postres.' in unescape(resp.data.decode())

    db.session.refresh(sub)
    assert (sub.name, sub.category_id) == ('Hand rolls', Category.query.filter_by(name='Sushi').one().id)


def test_a_subcategory_can_change_only_the_case_of_its_own_name(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='hand rolls')

    client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, name='Hand Rolls'))

    db.session.refresh(sub)
    assert sub.name == 'Hand Rolls'


# --- permissions: the same as deleting (any admin, owner or staff) ---

def test_editing_requires_login(client, db):
    sub = _create_subcategory(db, name='Hand rolls')
    category = Category.query.one()

    for url, data in ((f'/admin/categories/{category.id}/edit', {'name': 'hack'}),
                      (f'/admin/subcategories/{sub.id}/edit', _sub_form(sub, name='hack'))):
        assert client.get(url).status_code in (302, 401, 403)
        assert client.post(url, data=data).status_code in (302, 401, 403)

    db.session.expire_all()
    assert (Category.query.one().name, Subcategory.query.one().name) == ('Sushi', 'Hand rolls')


def test_a_non_admin_user_cannot_edit(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')
    category = Category.query.one()
    _login_as(client, db, 'cliente@test.com', is_admin=False)

    assert client.post(f'/admin/categories/{category.id}/edit', data={'name': 'hack'}).status_code == 403
    assert client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, name='hack')).status_code == 403


def test_staff_can_edit_like_they_can_delete(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')
    category = Category.query.one()
    _login_as(client, db, 'empleado@test.com', is_admin=True)

    client.post(f'/admin/categories/{category.id}/edit', data={'name': 'Sushi bar'})
    client.post(f'/admin/subcategories/{sub.id}/edit', data=_sub_form(sub, name='Handrolls'))

    db.session.expire_all()
    assert (Category.query.one().name, Subcategory.query.one().name) == ('Sushi bar', 'Handrolls')


# --- history ---

def test_a_past_order_does_not_change(client, db, order_payload):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls')
    sushi = Category.query.one()
    product = _create_product(db, sushi, sub, name='Hand pollo', price=2990)
    client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 2}]))
    order = Order.query.one()
    before = (order.total_price, [(i.product_name, i.quantity, i.price) for i in order.order_items])

    entradas = _create_category(db, 'Entradas')
    client.post(f'/admin/categories/{sushi.id}/edit', data={'name': 'Sushi bar'})
    client.post(f'/admin/subcategories/{sub.id}/edit',
                data=_sub_form(sub, name='Handrolls', category_id=str(entradas.id)))

    db.session.expire_all()
    order = Order.query.one()
    assert (order.total_price, [(i.product_name, i.quantity, i.price) for i in order.order_items]) == before
    assert before == (2 * 2990, [('Hand pollo', 2, 2990)])


# --- panel listing ---

def test_categories_panel_has_edit_next_to_delete(client, db):
    _register_owner(client)
    sub = _create_subcategory(db, name='Hand rolls', description='pollo, camarón, salmón')
    category = Category.query.one()

    html = client.get('/admin/categories').data.decode()

    assert '<small class="muted">pollo, camarón, salmón</small>' in html
    assert f'href="/admin/categories/{category.id}/edit"' in html
    assert f'href="/admin/subcategories/{sub.id}/edit"' in html


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
