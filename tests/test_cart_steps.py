"""The cart in two steps inside the same panel: what goes in each, in what order."""
import json

from app.models import DeliveryZone


def _menu(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})
    return client.get('/').get_data(as_text=True)


def _between(html, start, end):
    return html[html.index(start):html.index(end)]


def test_step_one_has_the_order_and_continue(client, db):
    html = _menu(client)
    step1 = _between(html, 'id="cart-step-1"', 'id="cart-step-2"')
    for marker in ('id="cart-step-1-title" tabindex="-1">Tu pedido<', 'id="cart-items"', 'id="upsell-suggestions"',
                   'id="gift-hint"', 'id="promo-nudges"', 'id="step-1-subtotal"', 'id="cart-continue"'):
        assert marker in step1, marker
    assert 'Continuar · <span id="cart-continue-total">' in step1
    # Nothing of the checkout lives in step 1.
    for marker in ('id="customer-name"', 'id="coupon-code"', 'id="checkout-btn"'):
        assert marker not in step1, marker


def test_step_two_has_the_checkout_in_order(client, db):
    polygon = {'type': 'Polygon', 'coordinates': [[[-71, -34], [-69, -34], [-69, -33], [-71, -33], [-71, -34]]]}
    db.session.add(DeliveryZone(name='Zona', price=1500, geojson=json.dumps(polygon)))
    db.session.commit()
    html = _menu(client)
    assert '<section id="cart-step-2" class="cart-step" aria-labelledby="cart-step-2-title" hidden>' in html
    start = html.index('id="cart-step-2"')
    step2 = html[start:html.index('</aside>', start)]
    assert '← Volver a tu pedido' in step2 and 'tabindex="-1">Finalizar pedido<' in step2
    order = ['id="delivery-mode-options"', 'id="delivery-status"', 'id="min-order-hint"',
             'id="delivery-address-block" class="delivery-address-block" hidden', 'id="address"', 'id="map"',
             'id="requested-time"', 'id="customer-name"', 'id="phone"', 'id="coupon-offers"',
             'id="coupon-code"', 'name="payment-method"', 'id="notes"', 'id="subtotal"', 'id="shipping"',
             'id="bundle-discount-rows"', 'id="discount-row"', 'id="total"', 'id="savings-note"', 'id="checkout-btn"']
    positions = [step2.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert 'Enviar por WhatsApp · <span id="checkout-total">' in step2


def test_both_steps_have_a_close_button(client, db):
    html = _menu(client)
    assert html.count('data-cart-close aria-label="Cerrar carrito"') == 2


def test_pickup_line_shows_the_business_address(client, db):
    html = _menu(client)
    assert 'data-pickup-address=""' in html and 'Retiro en el local · sin costo' in html
    assert html.index('delivery_status.js') < html.index('menu.js')
