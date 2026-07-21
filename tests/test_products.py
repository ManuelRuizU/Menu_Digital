import pytest

from app.models import Category, Product


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _create_category(db, name='Categoria'):
    category = Category(name=name)
    db.session.add(category)
    db.session.commit()
    return category


def _product_form_data(category_id, **overrides):
    data = {
        'name': 'Producto', 'description': 'Descripcion', 'price': 1000,
        'category_id': category_id,
    }
    data.update(overrides)
    return data


# --- prep_minutes: saved through the panel form (create_product / edit_product) ---

def test_create_product_with_valid_prep_minutes_persists_as_int(client, db):
    _register_owner(client)
    category = _create_category(db)

    resp = client.post('/admin/products/new', data=_product_form_data(category.id, prep_minutes=40))

    assert resp.status_code == 302
    product = Product.query.order_by(Product.id.desc()).first()
    assert product.prep_minutes == 40


def test_create_product_without_prep_minutes_saves_none(client, db):
    _register_owner(client)
    category = _create_category(db)

    resp = client.post('/admin/products/new', data=_product_form_data(category.id))

    assert resp.status_code == 302
    product = Product.query.order_by(Product.id.desc()).first()
    assert product.prep_minutes is None  # optional field, product works fine without it


@pytest.mark.parametrize('invalid_value', ['0', '-5', 'abc'])
def test_create_product_with_invalid_prep_minutes_saves_none_without_breaking(client, db, invalid_value):
    _register_owner(client)
    category = _create_category(db)

    resp = client.post('/admin/products/new', data=_product_form_data(category.id, prep_minutes=invalid_value))

    # An invalid value in this purely-informational field never blocks saving the product.
    assert resp.status_code == 302
    product = Product.query.order_by(Product.id.desc()).first()
    assert product is not None
    assert product.prep_minutes is None


def test_edit_product_updates_prep_minutes(client, db):
    _register_owner(client)
    category = _create_category(db)
    product = Product(name='Pizza', description='Familiar', price=8000, category_id=category.id, prep_minutes=20)
    db.session.add(product)
    db.session.commit()

    resp = client.post(f'/admin/products/{product.id}/edit',
                        data=_product_form_data(category.id, name='Pizza', prep_minutes=35))

    assert resp.status_code == 302
    db.session.refresh(product)
    assert product.prep_minutes == 35


# --- prep_minutes: exposed to the public menu via /api/products ---

def test_products_api_includes_prep_minutes(client, db):
    category = _create_category(db)
    with_prep = Product(name='Sushi 120pz', description='Test', price=25000,
                         category_id=category.id, is_active=True, prep_minutes=40)
    without_prep = Product(name='Bebida', description='Test', price=1500,
                            category_id=category.id, is_active=True)
    db.session.add_all([with_prep, without_prep])
    db.session.commit()

    resp = client.get('/api/products')

    assert resp.status_code == 200
    payload = {item['name']: item for item in resp.get_json()}
    assert payload['Sushi 120pz']['prepMinutes'] == 40
    # A product without prep_minutes must still serialize fine, just with null - not
    # missing the key entirely (the front-end checks for a falsy value, not a missing one).
    assert payload['Bebida']['prepMinutes'] is None


# --- product photo: framing warning + live crop preview (product_form.html, pure HTML/JS) ---

def test_create_product_form_shows_photo_framing_help_text(client, db):
    _register_owner(client)

    resp = client.get('/admin/products/new')
    html = resp.data.decode()

    assert resp.status_code == 200
    assert 'encuadra el plato al medio' in html
    assert 'Peso máximo: 12 MB' in html


def test_create_product_form_has_preview_container_hidden_when_no_photo_yet(client, db):
    _register_owner(client)

    resp = client.get('/admin/products/new')
    html = resp.data.decode()

    assert 'id="image-preview-block" style="display:none;"' in html
    assert 'id="image-preview" class="image-preview"' in html


def test_edit_product_form_shows_preview_of_existing_photo(client, db):
    _register_owner(client)
    category = _create_category(db)
    product = Product(name='Roll', description='Test', price=1000, category_id=category.id,
                       image_filename='product_1.jpg')
    db.session.add(product)
    db.session.commit()

    resp = client.get(f'/admin/products/{product.id}/edit')
    html = resp.data.decode()

    assert 'id="image-preview-block" style="">' in html  # visible - there's already a photo
    assert 'src="/static/uploads/products/product_1.jpg"' in html
