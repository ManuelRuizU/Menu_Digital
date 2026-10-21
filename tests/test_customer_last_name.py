"""The customer's last name: required by the current menu form, but an order from a menu
page loaded before the deploy (no customerLastName key) still goes through, with NULL.
Everywhere the panel names a customer, it's "Nombre Apellido"."""
import csv
from io import StringIO

from app.catalog.routes import _build_courier_message
from app.models import Category, Order, OrderItem, Product
from app.utils import phone_customer_key


def _register_owner(client):
    client.post('/register', data={'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123'})


def _product(db):
    category = Category(name='Carta')
    db.session.add(category)
    db.session.flush()
    product = Product(name='Bebida', description='T', price=1000, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


def _post(client, db, order_payload, **overrides):
    product = Product.query.first() or _product(db)
    return client.post('/api/orders', json=order_payload(items=[{'id': product.id, 'quantity': 1}], **overrides))


def _order(db, name='Manuel', last_name='Ruiz', phone='56911112222', **fields):
    order = Order(customer_name=name, customer_last_name=last_name, phone=phone, delivery_mode='retira',
                  payment_method='efectivo', total_price=1000, status='Pending', **fields)
    db.session.add(order)
    db.session.commit()
    return order


def test_new_form_requires_the_last_name(client, db, order_payload):
    for blank in ('', '   '):
        response = _post(client, db, order_payload, customerLastName=blank)
        assert response.status_code == 400
        assert response.get_json()['message'] == 'Falta indicar el apellido.'
    assert Order.query.count() == 0


def test_order_from_an_old_menu_page_without_last_name_is_accepted(client, db, order_payload):
    payload = order_payload()
    del payload['customerLastName']
    product = _product(db)
    payload['items'] = [{'id': product.id, 'quantity': 1}]
    payload['customerName'] = 'Manuel Ruiz Uribe'

    response = client.post('/api/orders', json=payload)

    assert response.status_code == 200, response.get_json()
    order = Order.query.one()
    assert order.customer_name == 'Manuel Ruiz Uribe'
    assert order.customer_last_name is None
    assert order.customer_full_name == 'Manuel Ruiz Uribe'


def test_names_are_trimmed_and_inner_spaces_collapsed(client, db, order_payload):
    response = _post(client, db, order_payload, customerName='  María   José ', customerLastName=' Soto   Pérez  ')

    assert response.status_code == 200, response.get_json()
    order = Order.query.one()
    assert (order.customer_name, order.customer_last_name) == ('María José', 'Soto Pérez')
    assert order.customer_full_name == 'María José Soto Pérez'


def test_names_over_60_characters_are_rejected(client, db, order_payload):
    response = _post(client, db, order_payload, customerLastName='x' * 61)
    assert response.get_json()['message'] == 'El apellido es muy largo.'
    response = _post(client, db, order_payload, customerName='x' * 61)
    assert response.get_json()['message'] == 'El nombre es muy largo.'
    assert _post(client, db, order_payload, customerLastName='x' * 60).status_code == 200


def test_non_text_last_name_is_treated_as_blank(client, db, order_payload):
    response = _post(client, db, order_payload, customerLastName=123)
    assert response.get_json()['message'] == 'Falta indicar el apellido.'


def test_panel_orders_and_courier_text_show_the_full_name(client, db):
    _register_owner(client)
    order = Order(customer_name='Manuel', customer_last_name='Ruiz', phone='56911112222', delivery_mode='envio',
                  address='Calle 1', payment_method='efectivo', total_price=1000, status='Confirmed', daily_number=1)
    db.session.add(order)
    db.session.commit()

    html = client.get('/admin/orders').get_data(as_text=True)
    assert 'Manuel Ruiz' in html
    assert 'Cliente: Manuel Ruiz\n' in _build_courier_message(order) + '\n'


def test_old_order_without_last_name_shows_its_name_alone(db):
    order = _order(db, name='manuel ruiz uribe', last_name=None)
    assert order.customer_full_name == 'manuel ruiz uribe'


def test_csv_keeps_cliente_and_adds_nombre_and_apellido_at_the_end(client, db):
    _register_owner(client)
    _order(db, name='Manuel', last_name='Ruiz')
    _order(db, name='Carolina González Mora', last_name=None)

    body = client.get('/admin/orders/export.csv').get_data(as_text=True).lstrip('﻿')
    rows = list(csv.reader(StringIO(body)))

    header = rows[0]
    assert header[5] == 'Cliente'
    assert header[-2:] == ['Nombre', 'Apellido']
    assert rows[1][5] == 'Manuel Ruiz' and rows[1][-2:] == ['Manuel', 'Ruiz']
    assert rows[2][5] == 'Carolina González Mora' and rows[2][-2:] == ['Carolina González Mora', '']


def test_phone_customer_key_keeps_the_last_nine_digits():
    assert phone_customer_key('+56 9 1234 5678') == '912345678'
    assert phone_customer_key('56912345678') == '912345678'
    assert phone_customer_key('912345678') == '912345678'
    assert phone_customer_key('9 1234-5678') == '912345678'
    assert phone_customer_key('12345') == '12345'


def test_dashboard_groups_customers_by_normalized_phone(client, db):
    _register_owner(client)
    _order(db, name='Primero', last_name='Pedido', phone='+56 9 1234 5678')
    _order(db, name='Segundo', last_name='Pedido', phone='56912345678')
    _order(db, name='Manuel', last_name='Ruiz', phone='912345678')
    _order(db, name='Otra', last_name='Persona', phone='56987654321')

    html = client.get('/admin/dashboard').get_data(as_text=True)

    assert html.count('class="card customer-card"') == 2
    assert 'Manuel Ruiz' in html and '3 pedido(s)' in html
    assert 'Primero Pedido' not in html and 'Segundo Pedido' not in html
    assert 'Otra Persona' in html and '1 pedido(s)' in html
