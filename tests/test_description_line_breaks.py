"""Descriptions keep the owner's line breaks from the panel to /api/products - the menu
then shows them (white-space: pre-line, see tests/js/description_format.test.js)."""
from app.models import Category, Product, Subcategory

CHEF = '70 piezas elegidas por el chef:\r\n10 piezas California\r\n10 piezas Ebi tempura\r\n\r\n10 piezas Sake'


def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _category(db):
    category = Category(name='Promos')
    db.session.add(category)
    db.session.commit()
    return category


def test_product_description_keeps_its_line_breaks(client, db):
    _register_owner(client)
    category = _category(db)
    client.post('/admin/products/new', data={'name': '70 del Chef', 'description': f'  {CHEF}  \r\n',
                                            'price': '29990', 'category_id': str(category.id)})

    product = Product.query.filter_by(name='70 del Chef').one()
    assert product.description == CHEF  # only the outer whitespace is trimmed
    api = client.get('/api/products').get_json()
    assert api[0]['description'].count('\n') == 4


def test_subcategory_description_is_a_textarea_and_keeps_line_breaks(client, db):
    _register_owner(client)
    category = _category(db)
    sub = Subcategory(name='Tablas', category_id=category.id)
    db.session.add(sub)
    db.session.commit()

    html = client.get(f'/admin/subcategories/{sub.id}/edit').get_data(as_text=True)
    assert '<textarea id="description" name="description"' in html

    client.post(f'/admin/subcategories/{sub.id}/edit',
                data={'name': 'Tablas', 'description': 'Para compartir\r\n- 40 piezas\r\n- 70 piezas',
                      'category_id': str(category.id)})
    assert db.session.get(Subcategory, sub.id).description == 'Para compartir\r\n- 40 piezas\r\n- 70 piezas'


def test_product_form_explains_line_breaks(client, db):
    _register_owner(client)
    html = client.get('/admin/products/new').get_data(as_text=True)
    assert 'Usa Enter para separar los ítems; se respeta en la carta' in html


def test_menu_loads_the_description_formatter_before_menu_js(client, db):
    html = client.get('/').get_data(as_text=True)
    assert html.index('js/description_format.js') < html.index('js/menu.js')
