"""Quantity pricing ("2 por $4.990, 3 por $6.990") configured from the product editor:
creating, replacing and removing the product's own tiered BundlePromo, its validations
against the price being saved, who may change it, and deleting a product that has it."""
import json
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path

import pytest

from werkzeug.security import generate_password_hash

from app.models import (BUSINESS_TZ, BundlePromo, BundlePromoTier, Category, Order, OrderItem, Product,
                        ProductOption, ProductOptionGroup, User)

UNIT = 2990


def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _login_as_staff(client, db):
    staff = User(username='empleado', email='empleado@test.com', password_hash=generate_password_hash('secret123'),
                 is_admin=True, is_owner=False)
    db.session.add(staff)
    db.session.commit()
    client.get('/logout')
    client.post('/login', data={'email': 'empleado@test.com', 'password': 'secret123'})


def _category(db):
    category = Category.query.first()
    if category is None:
        category = Category(name='Hand rolls')
        db.session.add(category)
        db.session.commit()
    return category


def _create_product(db, name='Hand roll pollo', price=UNIT):
    product = Product(name=name, description='Test', price=price, category_id=_category(db).id)
    db.session.add(product)
    db.session.commit()
    return product


def _create_tiered_promo(db, products, tiers=((2, 4990), (3, 6990)), label='Precio por cantidad - Hand roll pollo',
                         **fields):
    promo = BundlePromo(label=label, kind='tiered', **{'is_active': True, **fields})
    promo.tiers = [BundlePromoTier(quantity=q, total_price=price) for q, price in tiers]
    db.session.add(promo)
    db.session.flush()
    promo.products = products
    db.session.commit()
    return promo


def _form(db, name='Hand roll pollo', price=UNIT, tiers=(('2', '4990'), ('3', '6990'), ('', ''), ('', '')),
          enabled=True, featured='1', **overrides):
    """The product form as the owner's browser sends it: every tier row, blank ones too,
    the switch (an unchecked checkbox isn't sent) and the featured-price select."""
    data = {'name': name, 'description': 'Test', 'price': str(price), 'category_id': str(_category(db).id)}
    if tiers is not None:
        data['tier_quantity'] = [q for q, _price in tiers]
        data['tier_price'] = [price for _q, price in tiers]
        data['featured_quantity'] = featured
        if enabled:
            data['tiered_enabled'] = 'on'
    data.update(overrides)
    return data


def _edit(client, product, data):
    return client.post(f'/admin/products/{product.id}/edit', data=data, follow_redirects=True)


def _text(resp):
    return unescape(resp.data.decode())


def _today():
    return datetime.now(BUSINESS_TZ).date()


def _tiers(promo):
    return [(t.quantity, t.total_price) for t in promo.tiers]


# --- create / replace / remove ---

def test_new_product_with_tiers_creates_its_own_permanent_tiered_promo(client, db):
    _register_owner(client)

    client.post('/admin/products/new', data=_form(db, tiers=(('3', '6990'), ('', ''), ('2', '4990'))))

    product = Product.query.one()
    promo = BundlePromo.query.one()
    assert promo.kind == 'tiered'
    assert promo.products == [product]
    assert _tiers(promo) == [(2, 4990), (3, 6990)]
    assert promo.label == 'Precio por cantidad - Hand roll pollo'
    assert (promo.is_active, promo.valid_from, promo.valid_until) == (True, None, None)
    assert (promo.buy_quantity, promo.pay_quantity) == (None, None)


def test_switch_off_and_no_promo_creates_nothing(client, db):
    _register_owner(client)

    # Off, even with rows typed: only the regular price.
    client.post('/admin/products/new', data=_form(db, enabled=False))

    assert Product.query.count() == 1
    assert BundlePromo.query.count() == 0


def test_switch_on_without_any_tier_asks_for_one(client, db):
    _register_owner(client)

    resp = client.post('/admin/products/new', data=_form(db, tiers=(('', ''), ('', ''))), follow_redirects=True)

    assert 'Agrega al menos un nivel (ej. 2 por $4.990), o apaga el precio por cantidad.' in _text(resp)
    assert Product.query.count() == 0

def test_editing_replaces_the_tiers_keeping_a_quantity(client, db):
    # Old and new tier share quantity 2: replacing them must not trip unique(promo_id, quantity).
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])

    _edit(client, product, _form(db, tiers=(('2', '4500'), ('', ''))))

    db.session.expire_all()
    assert BundlePromo.query.one().id == promo.id
    assert _tiers(BundlePromo.query.one()) == [(2, 4500)]
    assert BundlePromoTier.query.count() == 1


def test_switching_off_keeps_the_tiers_and_stops_the_discount(client, db, order_payload):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product], featured_quantity=3)

    # Off with the rows edited in the same save: the saved tiers win, untouched.
    _edit(client, product, _form(db, enabled=False, tiers=(('2', '4000'), ('', ''))))

    db.session.expire_all()
    promo = BundlePromo.query.one()
    assert promo.is_active is False
    assert _tiers(promo) == [(2, 4990), (3, 6990)]
    assert promo.featured_quantity == 3
    assert client.get('/api/bundle-promos').get_json() == []

    client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 3}], phone='56911112222'))
    order = Order.query.one()
    assert (order.bundle_discount_amount, order.total_price) == (0, 3 * UNIT)


def test_the_editor_shows_switched_off_tiers_ready_to_switch_back_on(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product], is_active=False, featured_quantity=3)

    html = client.get(f'/admin/products/{product.id}/edit').data.decode()

    assert 'id="tiered_enabled" name="tiered_enabled" >' in html  # unchecked
    assert 'value="6990"' in html
    assert '<option value="3" selected>3 x $6990</option>' in html


def test_switching_back_on_restores_the_tiers(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product], is_active=False, featured_quantity=3)

    # What the editor sends when the owner just flips the switch: the saved rows as shown.
    _edit(client, product, _form(db, featured='3'))

    db.session.refresh(promo)
    assert promo.is_active is True
    assert _tiers(promo) == [(2, 4990), (3, 6990)]
    assert promo.featured_quantity == 3
    assert [p['id'] for p in client.get('/api/bundle-promos').get_json()] == [promo.id]


def test_a_price_change_while_switched_off_is_checked_when_switching_back_on(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product], is_active=False)

    # Off: its tiers don't apply, so a price that breaks them doesn't block saving.
    _edit(client, product, _form(db, price=2000, enabled=False))
    db.session.refresh(product)
    assert product.price == 2000

    resp = _edit(client, product, _form(db, price=2000))
    assert 'debe costar menos de $4000' in _text(resp)
    assert BundlePromo.query.one().is_active is False

def test_a_post_without_tier_fields_leaves_the_promo_alone(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])

    _edit(client, product, _form(db, tiers=None))

    db.session.expire_all()
    assert _tiers(BundlePromo.query.one()) == [(2, 4990), (3, 6990)]


def test_renaming_the_product_renames_the_promo(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])

    _edit(client, product, _form(db, name='Hand roll pollo teriyaki'))

    db.session.expire_all()
    assert BundlePromo.query.one().label == 'Precio por cantidad - Hand roll pollo teriyaki'


def test_saving_with_the_switch_on_makes_a_dated_promo_permanent(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product], valid_until=_today() + timedelta(days=3))

    _edit(client, product, _form(db))

    db.session.refresh(promo)
    assert (promo.is_active, promo.valid_from, promo.valid_until) == (True, None, None)


# --- the featured price ---

def test_the_featured_tier_is_saved_and_sent_to_the_menu(client, db):
    _register_owner(client)
    product = _create_product(db)

    _edit(client, product, _form(db, featured='3'))

    promo = BundlePromo.query.one()
    assert promo.featured_quantity == 3
    assert client.get('/api/bundle-promos').get_json()[0]['featuredQuantity'] == 3


def test_a_featured_quantity_that_is_not_a_tier_is_rejected(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product], featured_quantity=2)

    for featured in ('5', '0', 'abc', '-3'):
        resp = _edit(client, product, _form(db, featured=featured, tiers=(('2', '4500'), ('3', '6990'))))
        assert 'debe ser "Suelto" o uno de los niveles' in _text(resp), featured

    db.session.expire_all()
    promo = BundlePromo.query.one()
    assert (promo.featured_quantity, _tiers(promo)) == (2, [(2, 4990), (3, 6990)])


def test_deleting_the_featured_tier_goes_back_to_the_single_price(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product], featured_quantity=3)

    # Without JS the select still says 3, but the owner emptied that row.
    resp = _edit(client, product, _form(db, featured='3', tiers=(('2', '4990'), ('', ''))))

    assert 'Quitaste el nivel de 3, que era el destacado' in _text(resp)
    promo = BundlePromo.query.one()
    assert (promo.featured_quantity, _tiers(promo)) == (1, [(2, 4990)])


def test_a_new_product_can_feature_a_tier_typed_in_the_same_save(client, db):
    _register_owner(client)

    client.post('/admin/products/new', data=_form(db, featured='2'))

    assert BundlePromo.query.one().featured_quantity == 2


# --- warning: variants that look like the old hand-made packs ---

def _add_group(db, product, name, options):
    group = ProductOptionGroup(product_id=product.id, name=name, required=False, multi_select=False)
    db.session.add(group)
    db.session.flush()
    db.session.add_all([ProductOption(group_id=group.id, name=n, price_delta=delta) for n, delta in options])
    db.session.commit()
    return group


PACK_WARNING = 'Este grupo suma al precio; si era un pack, bórralo: el precio por cantidad ya lo cubre.'


def test_warns_on_a_paid_group_that_looks_like_quantities(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])
    _add_group(db, product, 'full', [('precio', 0), ('2x', 5000), ('3X', 6000)])
    _add_group(db, product, 'Pack', [('x6', 9000)])

    html = _text(client.get(f'/admin/products/{product.id}/edit'))

    assert html.count(PACK_WARNING) == 2


def test_no_pack_warning_for_regular_variants_free_ones_or_when_switched_off(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = _create_tiered_promo(db, [product])
    _add_group(db, product, 'Extras', [('Extra palta', 500), ('Xtra queso', 700)])
    _add_group(db, product, 'Relleno', [('3 quesos', 0)])
    assert PACK_WARNING not in _text(client.get(f'/admin/products/{product.id}/edit'))

    _add_group(db, product, 'full', [('2x', 5000)])
    promo.is_active = False
    db.session.commit()
    assert PACK_WARNING not in _text(client.get(f'/admin/products/{product.id}/edit'))

# --- validation ---

def test_rejects_malformed_tiers_and_keeps_what_was_typed(client, db):
    _register_owner(client)
    product = _create_product(db)
    cases = {
        (('2', ''),): 'Cada nivel necesita',
        (('', '4990'),): 'Cada nivel necesita',
        (('1', '2000'),): 'Cada nivel necesita',
        (('2', '0'),): 'Cada nivel necesita',
        (('2', '4990'), ('2', '4500')): 'No puedes repetir',
    }
    for tiers, message in cases.items():
        resp = _edit(client, product, _form(db, tiers=tiers))
        assert message in _text(resp), tiers
    assert BundlePromo.query.count() == 0

    resp = _edit(client, product, _form(db, tiers=(('2', '4990'), ('2', '4500'))))
    assert 'value="4500"' in resp.data.decode()


def test_blocks_a_tier_that_is_not_cheaper_than_singles_at_the_new_price(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])

    # The tiers are unchanged, but at $2.000 each, 2 for $4.990 is no discount.
    resp = _edit(client, product, _form(db, price=2000))

    assert 'el nivel de 2 ($4990) debe costar menos de $4000 (2 × $2000)' in _text(resp)
    db.session.refresh(product)
    assert product.price == UNIT


def test_blocks_a_tier_equal_to_the_singles_price(client, db):
    _register_owner(client)

    resp = client.post('/admin/products/new', data=_form(db, tiers=(('2', '5980'),)), follow_redirects=True)

    assert 'debe costar menos de $5980' in _text(resp)
    assert Product.query.count() == 0
    assert BundlePromo.query.count() == 0


def test_blocks_when_the_product_is_already_in_an_active_2x1(client, db):
    _register_owner(client)
    product = _create_product(db)
    two_for_one = BundlePromo(label='2x1 hand rolls', kind='buy_pay', buy_quantity=2, pay_quantity=1, is_active=True)
    two_for_one.products = [product]
    db.session.add(two_for_one)
    db.session.commit()

    resp = _edit(client, product, _form(db))

    assert '"Hand roll pollo" ya está en la promo "2x1 hand rolls"' in _text(resp)
    assert 'quítalo de esa promo primero' in _text(resp)
    assert BundlePromo.query.count() == 1


def test_a_2x1_that_already_ended_does_not_block(client, db):
    # Still switched on, but its last day is past: quantity pricing counts from today.
    _register_owner(client)
    product = _create_product(db)
    ended = BundlePromo(label='2x1 septiembre', kind='buy_pay', buy_quantity=2, pay_quantity=1, is_active=True,
                        valid_until=_today() - timedelta(days=1))
    ended.products = [product]
    db.session.add(ended)
    db.session.commit()

    _edit(client, product, _form(db))

    assert BundlePromo.query.filter_by(kind='tiered').count() == 1


def test_a_2x1_ending_today_or_starting_later_still_blocks(client, db):
    _register_owner(client)
    product = _create_product(db)
    for label, dates in (('2x1 hoy', {'valid_until': _today()}),
                         ('2x1 diciembre', {'valid_from': _today() + timedelta(days=30)})):
        promo = BundlePromo(label=label, kind='buy_pay', buy_quantity=2, pay_quantity=1, is_active=True, **dates)
        promo.products = [product]
        db.session.add(promo)
        db.session.commit()

        resp = _edit(client, product, _form(db))

        assert f'ya está en la promo "{label}"' in _text(resp)
        assert BundlePromo.query.filter_by(kind='tiered').count() == 0
        db.session.delete(promo)
        db.session.commit()


def test_an_inactive_2x1_does_not_block(client, db):
    _register_owner(client)
    product = _create_product(db)
    dormant = BundlePromo(label='2x1', kind='buy_pay', buy_quantity=2, pay_quantity=1, is_active=False)
    dormant.products = [product]
    db.session.add(dormant)
    db.session.commit()

    _edit(client, product, _form(db))

    assert BundlePromo.query.filter_by(kind='tiered').count() == 1


# --- in the cart: units of the same product with $0 variants ---

def test_one_product_with_three_free_fillings_counts_as_three_units(client, db, order_payload):
    # Hand roll with a required "Relleno" at $0: pollo + salmón + camarón are three units
    # of the same product, so they get the price of 3, not three singles.
    _register_owner(client)
    product = _create_product(db, 'Hand roll')
    group = ProductOptionGroup(product_id=product.id, name='Relleno', required=True, multi_select=False)
    db.session.add(group)
    db.session.flush()
    fillings = [ProductOption(group_id=group.id, name=name, price_delta=0) for name in ('Pollo', 'Salmón', 'Camarón')]
    db.session.add_all(fillings)
    db.session.commit()
    _edit(client, product, _form(db, name='Hand roll'))  # 2 por $4.990, 3 por $6.990

    resp = client.post('/api/orders', json=order_payload(
        items=[{'id': product.id, 'quantity': 1, 'options': [filling.id]} for filling in fillings],
        phone='56911112222'))

    assert resp.get_json()['ok'] is True
    order = Order.query.one()
    assert order.bundle_discount_amount == 3 * UNIT - 6990
    assert order.total_price == 6990


MODAL_CASES = json.loads((Path(__file__).parent / 'fixtures' / 'modal_cases.json').read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', MODAL_CASES, ids=[c['name'] for c in MODAL_CASES])
def test_the_server_charges_what_the_modal_and_the_cart_said(client, db, order_payload, case):
    # The same vectors tests/js/cart_lines.test.js runs through the modal and the cart:
    # one line of `quantity` units (what "Agregar N" sends) is stored as quantity=N, and
    # the order total is the modal's total.
    _register_owner(client)
    product = _create_product(db, 'Cheesecake', price=case['unit'])
    _create_tiered_promo(db, [product], tiers=[tuple(tier) for tier in case['tiers']])
    item = {'id': product.id, 'quantity': case['quantity']}
    if case['extra_per_unit']:
        group = _add_group(db, product, 'Extras', [('Extra', case['extra_per_unit'])])
        item['options'] = [group.options[0].id]

    resp = client.post('/api/orders', json=order_payload(items=[item], phone='56911112222'))

    assert resp.get_json()['ok'] is True
    assert OrderItem.query.one().quantity == case['quantity']
    assert Order.query.one().total_price == case['expected_total']


# --- the form ---

def test_form_shows_saved_tiers_with_their_saving_and_blank_rows(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])

    html = client.get(f'/admin/products/{product.id}/edit').data.decode()

    assert 'id="tiered_enabled" name="tiered_enabled" checked' in html
    assert 'ahorra $990' in html   # 2 x 2990 - 4990
    assert 'ahorra $1980' in html  # 3 x 2990 - 6990
    assert html.count('<input name="tier_quantity"') == 4  # 2 saved + 2 blank
    assert '+ Agregar nivel' in html


def test_new_product_form_offers_blank_rows(client, db):
    _register_owner(client)
    _category(db)

    html = client.get('/admin/products/new').data.decode()

    assert html.count('<input name="tier_quantity"') == 2
    assert 'id="tiered_enabled" name="tiered_enabled" >' in html  # off by default


def test_a_legacy_shared_promo_is_read_only_and_untouched(client, db):
    _register_owner(client)
    pollo, salmon = _create_product(db), _create_product(db, 'Hand roll salmón')
    _create_tiered_promo(db, [pollo, salmon], label='Hand rolls')

    html = _text(client.get(f'/admin/products/{pollo.id}/edit'))
    assert 'compartido con' in html and 'Hand roll salmón' in html
    assert '<input name="tier_quantity"' not in html

    # Even a crafted POST with tiers doesn't create a second promo or change the shared one.
    _edit(client, pollo, _form(db, tiers=(('2', '4000'),)))
    db.session.expire_all()
    assert BundlePromo.query.count() == 1
    assert _tiers(BundlePromo.query.one()) == [(2, 4990), (3, 6990)]


# --- staff (admin, not owner) ---

def test_staff_sees_the_tiers_read_only_and_cannot_change_them(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])
    _login_as_staff(client, db)

    html = _text(client.get(f'/admin/products/{product.id}/edit'))
    assert 'Solo el dueño puede cambiarlo' in html
    assert '<input name="tier_quantity"' not in html

    _edit(client, product, _form(db, tiers=(('', ''),)))       # would remove it
    _edit(client, product, _form(db, tiers=(('2', '4000'),)))  # would change it
    db.session.expire_all()
    assert _tiers(BundlePromo.query.one()) == [(2, 4990), (3, 6990)]


def test_staff_cannot_create_tiers(client, db):
    _register_owner(client)
    product = _create_product(db)
    _login_as_staff(client, db)

    _edit(client, product, _form(db))

    assert BundlePromo.query.count() == 0


def test_staff_price_change_that_breaks_a_tier_is_blocked(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])
    _login_as_staff(client, db)

    resp = _edit(client, product, _form(db, price=2000, tiers=None))

    assert 'Pídele al dueño' in _text(resp)
    db.session.refresh(product)
    assert product.price == UNIT


def test_staff_price_change_that_keeps_the_discount_saves(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])
    _login_as_staff(client, db)

    _edit(client, product, _form(db, price=3200, tiers=None))

    db.session.refresh(product)
    assert product.price == 3200


# --- deleting the product ---

def test_deleting_a_product_takes_its_own_tiered_promo_with_it(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])

    resp = client.post(f'/admin/products/{product.id}/delete', follow_redirects=True)

    assert 'Producto eliminado' in _text(resp)
    assert Product.query.count() == 0
    assert BundlePromo.query.count() == 0
    assert BundlePromoTier.query.count() == 0


def test_a_product_in_a_2x1_still_cannot_be_deleted(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_tiered_promo(db, [product])
    other = _create_product(db, 'Hand roll salmón')
    two_for_one = BundlePromo(label='2x1 viejo', kind='buy_pay', buy_quantity=2, pay_quantity=1, is_active=False)
    two_for_one.products = [product, other]
    db.session.add(two_for_one)
    db.session.commit()

    resp = client.post(f'/admin/products/{product.id}/delete', follow_redirects=True)

    text = _text(resp)
    assert "No se puede eliminar: está en la promo '2x1 viejo'" in text
    assert 'Precio por cantidad' not in text.split('No se puede eliminar')[1].split('.')[0]
    assert Product.query.count() == 2
