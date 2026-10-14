"""Panel for automatic promos: creating/editing buy_pay and tiered promos, their
validations, the one-active-promo-per-product rule, and the price-mismatch warnings."""
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


def test_create_requires_choosing_a_kind(client, db):
    _register_owner(client)
    product = _create_product(db)

    resp = _post_new(client, {'label': 'X', 'buy_quantity': '2', 'pay_quantity': '1', 'product_ids': [str(product.id)]})

    assert 'elige el tipo de promoción'.encode() in resp.data
    assert BundlePromo.query.count() == 0


def test_create_tiered_promo_saves_sorted_tiers_and_no_buy_pay(client, db):
    _register_owner(client)
    pollo, salmon = _create_product(db, 'Hand roll pollo'), _create_product(db, 'Hand roll salmón')

    # Rows out of order, plus the blank extra rows the form always sends.
    _post_new(client, _tiered_form([pollo, salmon], tiers=(('3', '6990'), ('', ''), ('2', '4990'), ('', ''))))

    promo = BundlePromo.query.one()
    assert promo.kind == 'tiered'
    assert (promo.buy_quantity, promo.pay_quantity) == (None, None)
    assert [(t.quantity, t.total_price) for t in promo.tiers] == [(2, 4990), (3, 6990)]
    assert {p.id for p in promo.products} == {pollo.id, salmon.id}


def test_tiered_rejects_missing_or_malformed_tiers(client, db):
    _register_owner(client)
    product = _create_product(db)
    cases = {
        (('', ''),): 'Agrega al menos un nivel',
        (('2', ''),): 'Cada nivel necesita',
        (('', '4990'),): 'Cada nivel necesita',
        (('1', '2000'),): 'Cada nivel necesita',
        (('2', '0'),): 'Cada nivel necesita',
        (('2', '4990'), ('2', '4500')): 'No puedes repetir',
    }
    for tiers, message in cases.items():
        resp = _post_new(client, _tiered_form([product], tiers=tiers))
        assert message.encode() in resp.data, tiers
    assert BundlePromo.query.count() == 0


def test_tiered_rejects_products_with_different_prices_listing_them(client, db):
    _register_owner(client)
    pollo = _create_product(db, 'Hand roll pollo', price=UNIT)
    premium = _create_product(db, 'Hand roll premium', price=3490)

    resp = _post_new(client, _tiered_form([pollo, premium]))

    html = resp.data.decode()
    assert 'deben tener el mismo precio' in html
    assert 'Hand roll pollo ($2990)' in html and 'Hand roll premium ($3490)' in html
    assert BundlePromo.query.count() == 0


def test_tiered_rejects_a_tier_that_is_not_cheaper_than_singles(client, db):
    _register_owner(client)
    product = _create_product(db)

    resp = _post_new(client, _tiered_form([product], tiers=(('2', '5980'),)))  # exactly 2 x 2990

    assert 'El nivel de 2 debe costar menos de $5980'.encode() in resp.data
    assert BundlePromo.query.count() == 0


# --- editing ---

def test_edit_tiered_changing_a_price_keeps_the_same_quantity(client, db):
    # Old and new tier share quantity 2: replacing them must not trip unique(promo_id, quantity).
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])

    client.post(f'/admin/bundle-promos/{promo.id}/edit',
                data=_tiered_form([product], tiers=(('2', '4500'), ('3', '6990'))))

    db.session.expire_all()
    promo = BundlePromo.query.one()
    assert [(t.quantity, t.total_price) for t in promo.tiers] == [(2, 4500), (3, 6990)]


def test_edit_tiered_can_drop_a_tier(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])

    client.post(f'/admin/bundle-promos/{promo.id}/edit',
                data=_tiered_form([product], tiers=(('2', '4990'), ('', ''))))

    db.session.expire_all()
    assert [(t.quantity, t.total_price) for t in BundlePromo.query.one().tiers] == [(2, 4990)]
    assert BundlePromoTier.query.count() == 1


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


def test_form_offers_kind_only_when_creating(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])

    new_html = client.get('/admin/bundle-promos/new').data.decode()
    edit_html = client.get(f'/admin/bundle-promos/{promo.id}/edit').data.decode()

    assert '<select id="kind" name="kind"' in new_html
    assert '<select id="kind"' not in edit_html
    assert 'El tipo no se puede cambiar' in edit_html


def test_edit_form_shows_saving_next_to_each_tier(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])

    html = client.get(f'/admin/bundle-promos/{promo.id}/edit').data.decode()

    assert 'ahorra $990' in html   # 2 x 2990 - 4990
    assert 'ahorra $1980' in html  # 3 x 2990 - 6990


# --- one active promo per product, for overlapping dates ---

def test_product_cannot_join_a_second_active_promo_with_overlapping_dates(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_buy_pay_promo(db, [product], label='2x1 viejo')

    resp = _post_new(client, _tiered_form([product]))

    assert '"Hand roll pollo" ya está en la promo "2x1 viejo"' in _text(resp)
    assert BundlePromo.query.count() == 1


def test_product_can_join_another_promo_when_dates_do_not_overlap(client, db):
    _register_owner(client)
    product = _create_product(db)
    today = date.today()
    _create_buy_pay_promo(db, [product], valid_from=today, valid_until=today + timedelta(days=7))

    _post_new(client, _tiered_form([product], valid_from=(today + timedelta(days=8)).isoformat()))

    assert BundlePromo.query.count() == 2


def test_an_inactive_promo_does_not_block_its_products(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_buy_pay_promo(db, [product], is_active=False)

    _post_new(client, _tiered_form([product]))

    assert BundlePromo.query.count() == 2


def test_editing_a_promo_does_not_conflict_with_itself(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])

    resp = client.post(f'/admin/bundle-promos/{promo.id}/edit', data=_tiered_form([product], label='Renombrada'),
                       follow_redirects=True)

    assert 'Promoción guardada'.encode() in resp.data
    assert BundlePromo.query.one().label == 'Renombrada'


def test_activating_a_promo_that_would_overlap_is_blocked(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_buy_pay_promo(db, [product], label='2x1 activo')
    dormant = _create_tiered_promo(db, [product], label='Por cantidad', is_active=False)

    resp = client.post(f'/admin/bundle-promos/{dormant.id}/toggle-active', follow_redirects=True)

    assert 'ya está en la promo "2x1 activo"' in _text(resp)
    db.session.refresh(dormant)
    assert dormant.is_active is False


# --- warnings: listing and product edit ---

def test_listing_flags_a_tiered_promo_whose_prices_drifted(client, db):
    _register_owner(client)
    pollo = _create_product(db, 'Hand roll pollo')
    premium = _create_product(db, 'Hand roll premium')
    _create_tiered_promo(db, [pollo, premium])
    premium.price = 3490
    db.session.commit()

    html = client.get('/admin/bundle-promos').data.decode()

    assert 'No se está aplicando: precios distintos' in html
    assert 'Hand roll pollo ($2990)' in html and 'Hand roll premium ($3490)' in html


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
