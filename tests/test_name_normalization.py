"""Catalog names compared with normalize_name (case, spaces and accents don't count) when
creating and editing categories, subcategories and products, saved with clean_name, and
`flask check-duplicates` for data saved before the rule."""
from html import unescape

import pytest

from app.duplicates import check_duplicates_command, find_duplicates
from app.models import Category, Product, Subcategory
from app.utils import clean_name, normalize_name


def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _category(db, name):
    category = Category(name=name)
    db.session.add(category)
    db.session.commit()
    return category


def _subcategory(db, category, name):
    sub = Subcategory(name=name, category_id=category.id)
    db.session.add(sub)
    db.session.commit()
    return sub


def _product(db, category, name, subcategory=None, **fields):
    product = Product(name=name, description='T', price=2990, category_id=category.id,
                      subcategory_id=subcategory.id if subcategory else None, **fields)
    db.session.add(product)
    db.session.commit()
    return product


def _text(resp):
    return unescape(resp.data.decode())


def _product_form(category, name, **overrides):
    data = {'name': name, 'description': 'Test', 'price': '2990', 'category_id': str(category.id)}
    data.update(overrides)
    return data


# --- the two functions ---

@pytest.mark.parametrize('a, b', [
    ('Sushi', 'sushi'), ('Sushi', 'SUSHI'), ('  Sushi ', 'sushi'),
    ('Hand  Roll', 'Hand Roll'), ('Hand\tRoll', 'hand roll'),
    ('Maracuyá', 'Maracuya'), ('CAFÉ', 'cafe'), ('Straße', 'STRASSE'),
])
def test_normalize_name_treats_these_as_the_same(a, b):
    assert normalize_name(a) == normalize_name(b)


@pytest.mark.parametrize('a, b', [
    ('Piña', 'Pina'), ('PIÑA', 'pina'), ('Año', 'Ano'), ('Ñandú', 'Nandu'),
])
def test_normalize_name_keeps_n_tilde_a_different_letter(a, b):
    assert normalize_name(a) != normalize_name(b)


@pytest.mark.parametrize('a, b', [
    ('Piña', 'PIÑA'), ('Piña', ' piña '),
    ('Piña', 'Pin\u0303a'),  # the same ñ typed decomposed: n + combining tilde
    ('Ñandú', 'ñandu'),       # the ú still loses its accent
])
def test_normalize_name_still_matches_the_same_n_tilde(a, b):
    assert normalize_name(a) == normalize_name(b)


def test_normalize_name_keeps_different_names_apart():
    assert normalize_name('Hand Roll') != normalize_name('Handroll')
    assert normalize_name('Roll 1') != normalize_name('Roll 2')


def test_clean_name_keeps_case_and_accents_and_collapses_spaces():
    assert clean_name('  Hand   Roll  Maracuyá ') == 'Hand Roll Maracuyá'
    assert clean_name(None) == ''


# --- categories: unique globally ---

@pytest.mark.parametrize('typed', ['sushi', 'SUSHI', '  Súshi  '])
def test_create_category_rejects_a_normalized_duplicate(client, db, typed):
    _register_owner(client)
    _category(db, 'Sushi')

    resp = client.post('/admin/categories/new', data={'name': typed}, follow_redirects=True)

    assert 'Ya existe una categoría con ese nombre.' in _text(resp)
    assert Category.query.count() == 1


def test_category_is_saved_as_typed_with_spaces_collapsed(client, db):
    _register_owner(client)

    client.post('/admin/categories/new', data={'name': '  Postres   y  Café '})

    assert Category.query.one().name == 'Postres y Café'


def test_edit_category_rejects_a_normalized_duplicate_and_not_itself(client, db):
    _register_owner(client)
    _category(db, 'Postres de Maracuyá')
    category = _category(db, 'Sushi')

    resp = client.post(f'/admin/categories/{category.id}/edit', data={'name': 'postres  de maracuya'})
    assert 'Ya existe una categoría con ese nombre.' in _text(resp)

    # Saving its own name unchanged - or only re-cased/re-spaced - isn't a clash.
    resp = client.post(f'/admin/categories/{category.id}/edit', data={'name': ' SUSHI '}, follow_redirects=True)
    assert 'Categoría guardada' in _text(resp)
    db.session.refresh(category)
    assert category.name == 'SUSHI'


# --- subcategories: unique within their category ---

def test_create_subcategory_rejects_a_normalized_duplicate_in_its_category_only(client, db):
    _register_owner(client)
    sushi, postres = _category(db, 'Sushi'), _category(db, 'Postres')
    _subcategory(db, sushi, 'Hand Roll')

    resp = client.post('/admin/subcategories/new', data={'name': 'hand  roll', 'category_id': sushi.id},
                       follow_redirects=True)
    assert 'Ya existe una subcategoría con ese nombre en esta categoría.' in _text(resp)

    client.post('/admin/subcategories/new', data={'name': 'Hand  Roll', 'category_id': postres.id})
    assert Subcategory.query.filter_by(category_id=postres.id).one().name == 'Hand Roll'


def test_edit_subcategory_rejects_a_normalized_duplicate_also_when_moving(client, db):
    _register_owner(client)
    sushi, postres = _category(db, 'Sushi'), _category(db, 'Postres')
    sub = _subcategory(db, sushi, 'Rolls')
    _subcategory(db, sushi, 'Clásicos')
    _subcategory(db, postres, 'Maracuyá')

    form = {'name': 'clasicos', 'description': '', 'category_id': str(sushi.id)}
    assert 'Ya existe una subcategoría con ese nombre en Sushi.' in _text(
        client.post(f'/admin/subcategories/{sub.id}/edit', data=form))

    form = {'name': 'MARACUYA', 'description': '', 'category_id': str(postres.id)}
    assert 'Ya existe una subcategoría con ese nombre en Postres.' in _text(
        client.post(f'/admin/subcategories/{sub.id}/edit', data=form))

    form = {'name': 'Rolls', 'description': '', 'category_id': str(sushi.id)}
    assert 'Subcategoría guardada' in _text(
        client.post(f'/admin/subcategories/{sub.id}/edit', data=form, follow_redirects=True))


# --- products: unique within their category ---

@pytest.mark.parametrize('typed', ['california roll', 'CALIFORNIA ROLL', 'California  Roll', ' Califórnia Roll '])
def test_create_product_rejects_a_normalized_duplicate_in_its_category(client, db, typed):
    _register_owner(client)
    sushi = _category(db, 'Sushi')
    _product(db, sushi, 'California Roll')

    resp = client.post('/admin/products/new', data=_product_form(sushi, typed), follow_redirects=True)

    assert "Ya existe 'California Roll' en Sushi." in _text(resp)
    assert Product.query.count() == 1


def test_pina_and_pina_with_n_tilde_are_different_products_but_maracuya_is_not(client, db):
    _register_owner(client)
    jugos = _category(db, 'Jugos')
    _product(db, jugos, 'Jugo de Piña')
    _product(db, jugos, 'Jugo de Maracuyá')

    resp = client.post('/admin/products/new', data=_product_form(jugos, 'Jugo de Pina'), follow_redirects=True)
    assert 'Producto guardado' in _text(resp)

    resp = client.post('/admin/products/new', data=_product_form(jugos, 'Jugo de Maracuya'), follow_redirects=True)
    assert "Ya existe 'Jugo de Maracuyá' en Jugos." in _text(resp)

    assert sorted(p.name for p in Product.query.all()) == ['Jugo de Maracuyá', 'Jugo de Pina', 'Jugo de Piña']


def test_a_product_name_can_repeat_in_another_category(client, db):
    _register_owner(client)
    sushi, promos = _category(db, 'Sushi'), _category(db, 'Promociones')
    _product(db, sushi, 'California Roll')

    client.post('/admin/products/new', data=_product_form(promos, 'California Roll'))

    assert Product.query.filter_by(category_id=promos.id).one().name == 'California Roll'


def test_an_inactive_product_still_counts(client, db):
    _register_owner(client)
    sushi = _category(db, 'Sushi')
    _product(db, sushi, 'Roll Dragon', is_active=False)

    resp = client.post('/admin/products/new', data=_product_form(sushi, 'roll dragon'), follow_redirects=True)

    assert "Ya existe 'Roll Dragon' en Sushi." in _text(resp)


def test_editing_a_product_without_changing_its_name_does_not_clash_with_itself(client, db):
    _register_owner(client)
    sushi = _category(db, 'Sushi')
    product = _product(db, sushi, 'California Roll')

    resp = client.post(f'/admin/products/{product.id}/edit', data=_product_form(sushi, 'California Roll', price='3200'),
                       follow_redirects=True)

    assert 'Producto guardado' in _text(resp)
    db.session.refresh(product)
    assert product.price == 3200


def test_renaming_or_moving_a_product_onto_another_ones_name_is_rejected(client, db):
    _register_owner(client)
    sushi, promos = _category(db, 'Sushi'), _category(db, 'Promociones')
    _product(db, sushi, 'California Roll')
    other = _product(db, sushi, 'Roll Dragon')
    promo_roll = _product(db, promos, 'California Roll')

    resp = client.post(f'/admin/products/{other.id}/edit', data=_product_form(sushi, 'CALIFORNIA ROLL'))
    assert "Ya existe 'California Roll' en Sushi." in _text(resp)

    resp = client.post(f'/admin/products/{promo_roll.id}/edit', data=_product_form(sushi, 'California Roll'))
    assert "Ya existe 'California Roll' en Sushi." in _text(resp)

    db.session.expire_all()
    assert (Product.query.get(other.id).name, Product.query.get(promo_roll.id).category_id) == ('Roll Dragon', promos.id)


def test_product_name_is_saved_with_spaces_collapsed(client, db):
    _register_owner(client)
    sushi = _category(db, 'Sushi')

    client.post('/admin/products/new', data=_product_form(sushi, '  Hand   Roll  Maracuyá '))

    assert Product.query.one().name == 'Hand Roll Maracuyá'


def test_moving_a_subcategory_is_blocked_if_a_product_would_clash_there(client, db):
    _register_owner(client)
    sushi, promos = _category(db, 'Sushi'), _category(db, 'Promociones')
    rolls = _subcategory(db, sushi, 'Rolls')
    moving = _product(db, sushi, 'California Roll', subcategory=rolls)
    _product(db, promos, 'california  roll')

    resp = client.post(f'/admin/subcategories/{rolls.id}/edit',
                       data={'name': 'Rolls', 'description': '', 'category_id': str(promos.id)})

    assert "No se puede mover: ya existe 'california  roll' en Promociones." in _text(resp)
    db.session.expire_all()
    assert (Subcategory.query.get(rolls.id).category_id, Product.query.get(moving.id).category_id) == (sushi.id, sushi.id)


# --- flask check-duplicates ---

def test_check_duplicates_lists_each_kind_and_exits_1(app, db):
    sushi, sushi_upper = _category(db, 'Sushi'), _category(db, 'SÚSHI')
    _subcategory(db, sushi, 'Hand Roll')
    _subcategory(db, sushi, 'hand  roll')
    _subcategory(db, sushi_upper, 'Hand Roll')  # another category: fine
    _product(db, sushi, 'Maracuyá')
    _product(db, sushi, 'maracuya', is_active=False)
    _product(db, sushi_upper, 'Maracuyá')  # another category: fine

    found = find_duplicates()
    assert [[row.name for row in group] for group in found['categories']] == [['Sushi', 'SÚSHI']]
    assert [[row.name for row in group] for group in found['subcategories']] == [['Hand Roll', 'hand  roll']]
    assert [[row.name for row in group] for group in found['products']] == [['Maracuyá', 'maracuya']]

    result = app.test_cli_runner().invoke(check_duplicates_command)
    assert result.exit_code == 1
    assert '"Maracuyá" en "Sushi" = #' in result.output
    assert '"maracuya" en "Sushi" (inactivo)' in result.output
    assert '3 grupo(s) para limpiar' in result.output


def test_check_duplicates_on_a_clean_catalog_exits_0(app, db):
    sushi = _category(db, 'Sushi')
    _product(db, sushi, 'California Roll')

    result = app.test_cli_runner().invoke(check_duplicates_command)

    assert result.exit_code == 0
    assert 'Sin duplicados.' in result.output
