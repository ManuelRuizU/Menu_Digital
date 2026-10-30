"""The top of the public menu: the big carousel (owner HeroBanners, then banner coupons),
"Promos", "Recomendados" and "Explora el menú" - plus the panel that manages banners."""
from datetime import date, timedelta
from io import BytesIO

import pytest
from PIL import Image

from app.models import Category, Coupon, HeroBanner, Product
from app.storefront import clp, explore_categories
from app.uploads import half_width_filename


def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _category(db, name='Sushi', **fields):
    category = Category(name=name, **fields)
    db.session.add(category)
    db.session.commit()
    return category


def _product(db, category, name='Roll', price=5000, **fields):
    product = Product(name=name, description='T', price=price, category_id=category.id, **fields)
    db.session.add(product)
    db.session.commit()
    return product


def _banner(db, **fields):
    defaults = dict(desktop_image='banner_x_desktop.jpg', is_active=True, position=0)
    defaults.update(fields)
    banner = HeroBanner(**defaults)
    db.session.add(banner)
    db.session.commit()
    return banner


def _png(width, height, color=(200, 80, 40)):
    buffer = BytesIO()
    Image.new('RGB', (width, height), color).save(buffer, format='PNG')
    buffer.seek(0)
    return buffer


@pytest.fixture
def upload_dirs(app, tmp_path):
    """Uploads go to a temp folder, never into app/static/uploads."""
    app.config['BANNER_UPLOAD_DIR'] = str(tmp_path / 'banners')
    app.config['CATEGORY_UPLOAD_DIR'] = str(tmp_path / 'categories')
    return tmp_path


def _home(client):
    return client.get('/').get_data(as_text=True)


def _banner_form(**overrides):
    data = {'title': 'Halloween', 'text': '', 'button_label': '', 'target_type': 'none',
            'valid_from': '', 'valid_until': '', 'is_active': 'on'}
    data.update(overrides)
    return data


# --- Banner validation (panel) -------------------------------------------------------

def test_new_banner_saves_desktop_at_1920_with_960_copy_and_mobile_at_1080(client, db, upload_dirs):
    _register_owner(client)
    response = client.post('/admin/banners/new', data=_banner_form(
        desktop_image=(_png(3000, 1000), 'grande.png'), mobile_image=(_png(1500, 1500), 'movil.png'),
    ), content_type='multipart/form-data')

    assert response.status_code == 302
    banner = HeroBanner.query.one()
    folder = upload_dirs / 'banners'
    assert Image.open(folder / banner.desktop_image).size == (1920, 640)
    assert Image.open(folder / half_width_filename(banner.desktop_image)).size == (960, 320)
    assert Image.open(folder / banner.mobile_image).size == (1080, 1080)
    assert banner.position == 0 and banner.is_active


def test_desktop_image_is_required_to_create(client, db, upload_dirs):
    _register_owner(client)
    html = client.post('/admin/banners/new', data=_banner_form(),
                       content_type='multipart/form-data').get_data(as_text=True)
    assert 'Sube la imagen de escritorio' in html
    assert HeroBanner.query.count() == 0


@pytest.mark.parametrize('overrides, message', [
    ({'title': 'x' * 81}, 'El título puede tener hasta 80'),
    ({'text': 'x' * 201}, 'El texto puede tener hasta 200'),
    ({'button_label': 'x' * 31, 'target_type': 'category'}, 'El texto del botón puede tener hasta 30'),
    ({'button_label': 'Ver'}, 'El botón necesita un destino'),
    ({'target_type': 'category', 'target_category_id': '999', 'button_label': 'Ver'}, 'Elige una categoría'),
    ({'target_type': 'product', 'target_product_id': '999', 'button_label': 'Ver'}, 'Elige un producto activo'),
    ({'target_type': 'weird'}, 'Elige a dónde lleva el botón'),
    ({'valid_from': '2026-11-10', 'valid_until': '2026-11-01'}, 'no puede ser posterior'),
    ({'valid_from': 'mañana'}, 'no es válida'),
])
def test_invalid_banner_is_rejected_and_keeps_what_was_typed(client, db, upload_dirs, overrides, message):
    _register_owner(client)
    data = _banner_form(desktop_image=(_png(1920, 640), 'b.png'), **overrides)
    html = client.post('/admin/banners/new', data=data, content_type='multipart/form-data').get_data(as_text=True)
    assert message in html
    assert HeroBanner.query.count() == 0
    assert not (upload_dirs / 'banners').exists() or not any((upload_dirs / 'banners').iterdir())


def test_button_target_without_label_is_rejected(client, db, upload_dirs):
    _register_owner(client)
    category = _category(db)
    data = _banner_form(desktop_image=(_png(1920, 640), 'b.png'), target_type='category',
                        target_category_id=str(category.id))
    html = client.post('/admin/banners/new', data=data, content_type='multipart/form-data').get_data(as_text=True)
    assert 'Escribe el texto del botón' in html


def test_inactive_product_cannot_be_a_button_target(client, db, upload_dirs):
    _register_owner(client)
    product = _product(db, _category(db), is_active=False)
    data = _banner_form(desktop_image=(_png(1920, 640), 'b.png'), target_type='product',
                        target_product_id=str(product.id), button_label='Ver')
    html = client.post('/admin/banners/new', data=data, content_type='multipart/form-data').get_data(as_text=True)
    assert 'Elige un producto activo' in html


def test_sixth_active_banner_is_blocked_on_create_and_on_activate(client, db, upload_dirs):
    _register_owner(client)
    for position in range(5):
        _banner(db, position=position)
    inactive = _banner(db, is_active=False, position=5)

    html = client.post('/admin/banners/new', data=_banner_form(desktop_image=(_png(1920, 640), 'b.png')),
                       content_type='multipart/form-data').get_data(as_text=True)
    assert 'Ya hay 5 banners activos' in html
    assert HeroBanner.query.count() == 6

    client.post(f'/admin/banners/{inactive.id}/toggle-active')
    assert db.session.get(HeroBanner, inactive.id).is_active is False

    # An inactive one can still be created, and an active one can still be edited.
    client.post('/admin/banners/new', data=_banner_form(desktop_image=(_png(1920, 640), 'b.png'), is_active=''),
                content_type='multipart/form-data')
    assert HeroBanner.query.count() == 7
    first = HeroBanner.query.filter_by(position=0).first()
    client.post(f'/admin/banners/{first.id}/edit', data=_banner_form(title='Editado'),
                content_type='multipart/form-data')
    assert db.session.get(HeroBanner, first.id).title == 'Editado'


def test_move_up_and_down_reorders(client, db):
    _register_owner(client)
    a, b, c = (_banner(db, title=t, position=i) for i, t in enumerate('ABC'))
    client.post(f'/admin/banners/{c.id}/move/up')
    order = [banner.title for banner in HeroBanner.query.order_by(HeroBanner.position)]
    assert order == ['A', 'C', 'B']
    client.post(f'/admin/banners/{a.id}/move/down')
    assert [banner.title for banner in HeroBanner.query.order_by(HeroBanner.position)] == ['C', 'A', 'B']


def test_banners_panel_is_owner_only(client, db):
    assert client.get('/admin/banners').status_code in (302, 401, 403)


def test_product_and_category_targeted_by_a_banner_cannot_be_deleted(client, db):
    _register_owner(client)
    category = _category(db)
    product = _product(db, category)
    _banner(db, target_type='product', target_product_id=product.id, button_label='Ver')
    _banner(db, target_type='category', target_category_id=category.id, button_label='Ver')

    client.post(f'/admin/products/{product.id}/delete')
    client.post(f'/admin/categories/{category.id}/delete')

    assert db.session.get(Product, product.id) is not None
    assert db.session.get(Category, category.id) is not None


# --- The carousel on the menu --------------------------------------------------------

def test_no_banners_and_no_coupons_means_no_carousel(client, db):
    assert 'id="hero-carousel"' not in _home(client)


def test_first_slide_is_high_priority_and_the_rest_lazy(client, db):
    _banner(db, title='Uno', position=0)
    _banner(db, title='Dos', position=1)
    html = _home(client)
    first, second = html.split('class="hero-img"')[1:3]
    assert 'fetchpriority="high"' in first.split('>')[0] and 'loading="lazy"' not in first.split('>')[0]
    assert 'loading="lazy"' in second.split('>')[0]
    assert html.count('data-slide=') == 2 and 'hero-arrow-next' in html


def test_single_slide_is_static_without_dots_or_arrows(client, db):
    _banner(db, title='Solo')
    html = _home(client)
    assert 'hero-carousel is-single' in html
    assert 'hero-dot' not in html and 'hero-arrow' not in html


def test_mobile_image_goes_in_a_picture_source(client, db):
    _banner(db, mobile_image='banner_x_mobile.jpg')
    html = _home(client)
    assert '<source media="(max-width: 640px)" srcset="/static/uploads/banners/banner_x_mobile.jpg">' in html


def test_banner_texts_are_escaped(client, db):
    _banner(db, title='<script>alert(1)</script>', text='"Rico" & <b>barato</b>')
    html = _home(client)
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '&lt;b&gt;barato&lt;/b&gt;' in html


def test_inactive_and_out_of_date_banners_are_hidden(client, db):
    today = date.today()
    _banner(db, title='Apagado', is_active=False)
    _banner(db, title='Futuro', valid_from=today + timedelta(days=3))
    _banner(db, title='Vencido', valid_until=today - timedelta(days=3))
    _banner(db, title='Vigente', valid_from=today - timedelta(days=1), valid_until=today + timedelta(days=1))
    html = _home(client)
    assert 'Vigente' in html
    assert 'Apagado' not in html and 'Futuro' not in html and 'Vencido' not in html


def test_button_opens_the_product_or_scrolls_to_the_category(client, db):
    category = _category(db)
    product = _product(db, category)
    _banner(db, title='P', button_label='Ver roll', target_type='product', target_product_id=product.id)
    _banner(db, title='C', button_label='Ver sushi', target_type='category', target_category_id=category.id, position=1)
    html = _home(client)
    assert f'data-details="{product.id}">Ver roll</button>' in html
    assert f'data-target="cat-{category.id}">Ver sushi</button>' in html


def test_banner_for_a_sold_out_or_inactive_product_shows_without_button(client, db):
    category = _category(db)
    sold_out = _product(db, category, name='Agotado', sold_out=True)
    _banner(db, title='Sin stock', button_label='Pedir', target_type='product', target_product_id=sold_out.id)
    html = _home(client)
    assert 'Sin stock' in html
    assert 'class="hero-cta"' not in html and 'Pedir' not in html


def test_coupons_follow_the_banners_and_one_without_image_shows_the_discount(client, db):
    _banner(db, title='Manual')
    db.session.add(Coupon(code='DIEZ', discount_percent=10, scope='order', is_active=True, show_in_banner=True))
    db.session.commit()
    html = _home(client)
    assert html.index('Manual') < html.index('data-coupon-code="DIEZ"')
    coupon_slide = html.split('data-coupon-code="DIEZ"')[1]
    assert 'class="hero-big">-10%<' in coupon_slide and 'class="hero-code">DIEZ<' in coupon_slide


def test_only_a_coupon_still_shows_the_carousel(client, db):
    db.session.add(Coupon(code='DIEZ', discount_percent=10, scope='order', is_active=True, show_in_banner=True))
    db.session.commit()
    assert 'id="hero-carousel"' in _home(client)


# --- Promos / Recomendados / Explora el menú -----------------------------------------

def test_no_promos_or_recomendados_rows_and_featured_products_stay_out_of_the_carousel(client, db):
    category = _category(db)
    _product(db, category, name='Estrella uno', is_featured=True, image_filename='product_1.jpg')
    _product(db, category, name='Estrella dos', is_featured=True)
    _product(db, category, name='Oferta', price=900, original_price=1000)
    html = _home(client)
    assert 'home-promos-title' not in html and 'home-featured-title' not in html
    assert 'id="hero-carousel"' not in html  # featured products alone don't make slides


def test_explore_uses_category_image_then_first_product_photo_then_color(app, db):
    with_image = _category(db, name='Postres', image_filename='category_1_ab.jpg')
    _product(db, with_image, name='Mochi', image_filename='product_9.jpg')
    from_product = _category(db, name='Sushi')
    _product(db, from_product, name='A sin foto')
    _product(db, from_product, name='B con foto', image_filename='product_2.jpg')
    plain = _category(db, name='Bebidas')
    _product(db, plain, name='Agua')
    hidden = _category(db, name='Oculta')
    _product(db, hidden, name='Inactivo', is_active=False)

    products = Product.query.order_by(Product.category_id, Product.name).all()
    with app.test_request_context():
        tiles = {tile['name']: tile['image'] for tile in explore_categories(products)}
    assert tiles == {
        'Postres': '/static/uploads/categories/category_1_ab.jpg',
        'Sushi': '/static/uploads/products/product_2.jpg',
        'Bebidas': None,
    }


def _categories_with_products(db, count):
    for index in range(count):
        _product(db, _category(db, name=f'Categoria {index}'), name=f'Producto {index}')


def test_explore_title_and_four_categories_are_a_static_grid(client, db):
    _categories_with_products(db, 4)
    html = _home(client)
    assert 'Explora nuestro menú' in html
    assert 'class="home-row explore is-static"' in html
    assert 'explore-arrow' not in html
    assert html.count('class="explore-tile-name"') == 4


def test_more_than_four_categories_slide_with_labelled_arrows(client, db):
    _categories_with_products(db, 6)
    html = _home(client)
    assert 'class="home-row explore"' in html
    assert 'aria-label="Ver categorías anteriores"' in html and 'aria-label="Ver más categorías"' in html
    assert 'explore_scroller.js' in html
    assert html.count('class="explore-tile-name"') == 6


def test_explore_tiles_scroll_to_their_section(client, db):
    category = _category(db, name='Bebidas')
    _product(db, category, name='Agua')
    html = _home(client)
    assert f'class="explore-tile no-image" data-target="cat-{category.id}"' in html


def test_category_image_upload_and_removal(client, db, upload_dirs):
    _register_owner(client)
    category = _category(db, name='Postres')
    client.post(f'/admin/categories/{category.id}/edit', data={'name': 'Postres', 'image': (_png(1200, 800), 'p.png')},
                content_type='multipart/form-data')
    saved = db.session.get(Category, category.id).image_filename
    assert saved and Image.open(upload_dirs / 'categories' / saved).size == (800, 533)

    client.post(f'/admin/categories/{category.id}/edit', data={'name': 'Postres', 'remove_image': 'on'},
                content_type='multipart/form-data')
    assert db.session.get(Category, category.id).image_filename is None
    assert not (upload_dirs / 'categories' / saved).exists()


# --- Header ----------------------------------------------------------------------------

def test_clp_formats_like_the_menu():
    assert clp(8990) == '$8.990' and clp(1500000) == '$1.500.000' and clp(0) == '$0'


def test_coupon_box_comes_after_delivery_address_and_phone(client, db):
    # Changing the delivery mode or the address drops an applied coupon, so the box sits
    # after them (and after the phone, which per-customer coupons need) - before payment.
    _register_owner(client)
    html = _home(client)
    assert ('<label for="coupon-code" class="coupon-title"><span aria-hidden="true">🏷️</span> '
            '<span id="coupon-title-text">¿Tienes un código de descuento?</span></label>') in html
    positions = [html.index(marker) for marker in
                 ('id="address"', 'id="phone"', 'id="coupon-code"', 'name="payment-method"', 'id="checkout-btn"')]
    assert positions == sorted(positions)
