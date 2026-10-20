"""Panel for automatic promos: Promociones creates/edits only buy_pay (2x1/3x2) promos -
tiered ones are summarised there and edited from their product (test_product_tiered.py) -
plus the one-active-promo-per-product rule and the price-mismatch warnings."""
from datetime import date, timedelta
from html import unescape

from app.models import BundlePromo, BundlePromoTier, Category, Product

UNIT = 2990


def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _create_product(db, name='Hand roll pollo', price=UNIT):
    category = Category.query.first()
    if category is None:
        category = Category(name='Hand rolls')
        db.session.add(category)
        db.session.commit()
    product = Product(name=name, description='Test', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


def _tiered_form(products, tiers=(('2', '4990'), ('3', '6990')), **overrides):
    data = {
        'label': 'Hand rolls', 'kind': 'tiered',
        'product_ids': [str(p.id) for p in products],
        'tier_quantity': [q for q, _price in tiers],
        'tier_price': [price for _q, price in tiers],
    }
    data.update(overrides)
    return data


def _buy_pay_form(products, **overrides):
    data = {'label': '2x1', 'buy_quantity': '2', 'pay_quantity': '1',
            'product_ids': [str(p.id) for p in products]}
    data.update(overrides)
    return data


def _create_tiered_promo(db, products, tiers=((2, 4990), (3, 6990)), label='Hand rolls', **fields):
    promo = BundlePromo(label=label, kind='tiered', **{'is_active': True, **fields})
    promo.tiers = [BundlePromoTier(quantity=q, total_price=price) for q, price in tiers]
    db.session.add(promo)
    db.session.flush()
    promo.products = products
    db.session.commit()
    return promo


def _create_buy_pay_promo(db, products, label='2x1', **fields):
    promo = BundlePromo(label=label, kind='buy_pay', buy_quantity=2, pay_quantity=1, **{'is_active': True, **fields})
    db.session.add(promo)
    db.session.flush()
    promo.products = products
    db.session.commit()
    return promo


def _text(resp):
    """The page as the owner reads it - flash messages escape their quotes in the HTML."""
    return unescape(resp.data.decode())


def _post_new(client, data):
    return client.post('/admin/bundle-promos/new', data=data, follow_redirects=True)


# --- creating ---

def test_create_buy_pay_promo_still_works(client, db):
    _register_owner(client)
    product = _create_product(db, 'Bebida', price=1500)

    _post_new(client, {'label': '2x1 bebidas', 'kind': 'buy_pay', 'buy_quantity': '2', 'pay_quantity': '1',
                       'product_ids': [str(product.id)]})

    promo = BundlePromo.query.one()
    assert (promo.kind, promo.buy_quantity, promo.pay_quantity, promo.tiers) == ('buy_pay', 2, 1, [])


def test_create_without_a_kind_is_a_buy_pay(client, db):
    # The form no longer sends a kind - Promociones only makes 2x1/3x2.
    _register_owner(client)
    product = _create_product(db)

    _post_new(client, _buy_pay_form([product]))

    promo = BundlePromo.query.one()
    assert (promo.kind, promo.buy_quantity, promo.pay_quantity) == ('buy_pay', 2, 1)


def test_a_crafted_tiered_post_never_creates_a_tiered_promo(client, db):
    # Quantity pricing moved to the product editor: kind=tiered from here is ignored.
    _register_owner(client)
    product = _create_product(db)

    resp = _post_new(client, _tiered_form([product]))  # no buy/pay numbers
    assert 'Completa una combinación válida'.encode() in resp.data
    assert BundlePromo.query.count() == 0

    _post_new(client, _tiered_form([product], buy_quantity='3', pay_quantity='2'))
    promo = BundlePromo.query.one()
    assert (promo.kind, promo.buy_quantity, promo.pay_quantity, promo.tiers) == ('buy_pay', 3, 2, [])


def test_form_no_longer_offers_tiered(client, db):
    _register_owner(client)

    html = client.get('/admin/bundle-promos/new').data.decode()

    assert 'name="kind"' not in html
    assert 'tier_quantity' not in html
    assert 'Precio por cantidad' in html  # points the owner to the product editor


# --- editing ---

def test_edit_never_changes_the_kind(client, db):
    _register_owner(client)
    product = _create_product(db, 'Bebida', price=1500)
    promo = _create_buy_pay_promo(db, [product])

    # A crafted POST asking for tiered: ignored, the promo stays a 2x1 and is validated as one.
    client.post(f'/admin/bundle-promos/{promo.id}/edit', data={
        'label': '3x2', 'kind': 'tiered', 'buy_quantity': '3', 'pay_quantity': '2',
        'product_ids': [str(product.id)], 'tier_quantity': ['2'], 'tier_price': ['1000']})

    db.session.expire_all()
    promo = BundlePromo.query.one()
    assert (promo.kind, promo.buy_quantity, promo.pay_quantity, promo.tiers) == ('buy_pay', 3, 2, [])


def test_editing_a_tiered_promo_goes_to_its_product(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])

    for method in (client.get, client.post):
        resp = method(f'/admin/bundle-promos/{promo.id}/edit', data=_tiered_form([product], tiers=(('2', '100'),)))
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/admin/products/{product.id}/edit')

    db.session.expire_all()
    assert [(t.quantity, t.total_price) for t in BundlePromo.query.one().tiers] == [(2, 4990), (3, 6990)]


def test_a_legacy_shared_tiered_promo_is_not_editable(client, db):
    _register_owner(client)
    pollo, salmon = _create_product(db, 'Hand roll pollo'), _create_product(db, 'Hand roll salmón')
    promo = _create_tiered_promo(db, [pollo, salmon])

    resp = client.get(f'/admin/bundle-promos/{promo.id}/edit', follow_redirects=True)

    assert 'ya no se edita' in _text(resp)


def test_a_tiered_promo_cannot_be_toggled_from_promociones(client, db):
    _register_owner(client)
    promo = _create_tiered_promo(db, [_create_product(db)])

    resp = client.post(f'/admin/bundle-promos/{promo.id}/toggle-active', follow_redirects=True)

    assert 'se enciende o apaga desde el editor del producto' in _text(resp)
    db.session.refresh(promo)
    assert promo.is_active is True


# --- one active promo per product, for overlapping dates ---

def test_product_cannot_join_a_second_active_promo_with_overlapping_dates(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product], label='Precio por cantidad - Hand roll pollo')

    resp = _post_new(client, _buy_pay_form([product]))

    assert '"Hand roll pollo" ya está en la promo "Precio por cantidad - Hand roll pollo"' in _text(resp)
    assert BundlePromo.query.count() == 1


def test_product_can_join_another_promo_when_dates_do_not_overlap(client, db):
    _register_owner(client)
    product = _create_product(db)
    today = date.today()
    _create_buy_pay_promo(db, [product], valid_from=today, valid_until=today + timedelta(days=7))

    _post_new(client, _buy_pay_form([product], valid_from=(today + timedelta(days=8)).isoformat()))

    assert BundlePromo.query.count() == 2


def test_an_inactive_promo_does_not_block_its_products(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_buy_pay_promo(db, [product], is_active=False)

    _post_new(client, _buy_pay_form([product]))

    assert BundlePromo.query.count() == 2


def test_editing_a_promo_does_not_conflict_with_itself(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_buy_pay_promo(db, [product])

    resp = client.post(f'/admin/bundle-promos/{promo.id}/edit', data=_buy_pay_form([product], label='Renombrada'),
                       follow_redirects=True)

    assert 'Promoción guardada'.encode() in resp.data
    assert BundlePromo.query.one().label == 'Renombrada'


def test_activating_a_promo_that_would_overlap_is_blocked(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product], label='Precio por cantidad - Hand roll pollo')
    dormant = _create_buy_pay_promo(db, [product], label='2x1', is_active=False)

    resp = client.post(f'/admin/bundle-promos/{dormant.id}/toggle-active', follow_redirects=True)

    assert 'ya está en la promo "Precio por cantidad - Hand roll pollo"' in _text(resp)
    db.session.refresh(dormant)
    assert dormant.is_active is False


# --- listing and warnings ---

def test_listing_separates_quantity_pricing_and_links_to_the_product(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])

    html = client.get('/admin/bundle-promos').data.decode()

    assert f'/admin/products/{product.id}/edit' in html
    assert 'Ningún producto tiene precio por cantidad' not in html


def test_listing_flags_a_legacy_shared_tiered_promo_whose_prices_drifted(client, db):
    _register_owner(client)
    pollo = _create_product(db, 'Hand roll pollo')
    premium = _create_product(db, 'Hand roll premium')
    _create_tiered_promo(db, [pollo, premium])
    premium.price = 3490
    db.session.commit()

    html = client.get('/admin/bundle-promos').data.decode()

    assert 'compartido entre varios productos' in html
    assert 'no se está aplicando: precios distintos' in html
    assert 'Hand roll pollo $2990' in html and 'Hand roll premium $3490' in html


def test_listing_shows_tiers_with_savings_when_prices_match(client, db):
    _register_owner(client)
    _create_tiered_promo(db, [_create_product(db)])

    html = client.get('/admin/bundle-promos').data.decode()

    assert 'No se está aplicando' not in html
    assert '2 por $4990' in html and '(ahorra $990)' in html


def _edit_product_price(client, product, price):
    return client.post(f'/admin/products/{product.id}/edit', data={
        'name': product.name, 'description': 'Test', 'price': str(price), 'category_id': product.category_id,
    }, follow_redirects=True)


def test_editing_a_product_price_out_of_its_tiered_promo_warns_but_saves(client, db):
    _register_owner(client)
    pollo = _create_product(db, 'Hand roll pollo')
    premium = _create_product(db, 'Hand roll premium')
    _create_tiered_promo(db, [pollo, premium], label='Hand rolls')

    resp = _edit_product_price(client, premium, 3490)

    assert 'Este producto está en la promo "Hand rolls"' in _text(resp)
    db.session.refresh(premium)
    assert premium.price == 3490


def test_no_warning_when_the_new_price_keeps_the_promo_consistent(client, db):
    _register_owner(client)
    only = _create_product(db, 'Hand roll pollo')
    _create_tiered_promo(db, [only])

    resp = _edit_product_price(client, only, 3200)  # a single product always "matches"

    assert 'Este producto está en la promo'.encode() not in resp.data


def test_no_warning_for_mixed_prices_in_a_buy_pay_promo(client, db):
    _register_owner(client)
    jugo = _create_product(db, 'Jugo', price=4200)
    te = _create_product(db, 'Té', price=3800)
    _create_buy_pay_promo(db, [jugo, te])

    resp = _edit_product_price(client, te, 3900)

    assert 'Este producto está en la promo'.encode() not in resp.data


def test_listing_warns_on_both_promos_when_a_product_is_in_two_active_overlapping_promos(client, db):
    # Can't be created through the panel anymore - this is data from before the rule.
    _register_owner(client)
    shared = _create_product(db, 'Hand roll pollo')
    _create_buy_pay_promo(db, [shared], label='2x1 viejo')
    _create_tiered_promo(db, [shared], label='Hand rolls')

    html = _text(client.get('/admin/bundle-promos'))

    assert '⚠ El producto Hand roll pollo también está en la promo Hand rolls; los descuentos se suman.' in html
    assert '⚠ El producto Hand roll pollo también está en la promo 2x1 viejo; los descuentos se suman.' in html


def test_listing_does_not_warn_when_one_promo_is_inactive_or_dates_do_not_cross(client, db):
    _register_owner(client)
    shared = _create_product(db, 'Hand roll pollo')
    today = date.today()
    _create_buy_pay_promo(db, [shared], label='Pasada', valid_until=today - timedelta(days=10))
    _create_tiered_promo(db, [shared], label='Actual', valid_from=today)
    _create_buy_pay_promo(db, [shared], label='Apagada', is_active=False)

    html = _text(client.get('/admin/bundle-promos'))

    assert 'los descuentos se suman' not in html
