import urllib.error
from unittest.mock import MagicMock, patch

from app.catalog import routes as catalog_routes
from app.geocoding import geocode
from app.models import Category, Order, OrderItem, Product


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _create_product(db, price=1000, name='Producto'):
    category = Category(name='Categoria')
    db.session.add(category)
    db.session.commit()
    product = Product(name=name, description='Test', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


def _create_order(db, product, status='Confirmed', delivery_mode='envio', daily_number=None,
                   customer_name='Cliente', latitude=None, longitude=None, requested_time='19:00'):
    order = Order(customer_name=customer_name, phone='56911112222', delivery_mode=delivery_mode,
                  payment_method='efectivo', total_price=product.price, status=status,
                  requested_time=requested_time, daily_number=daily_number,
                  latitude=latitude, longitude=longitude)
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=product.price))
    db.session.commit()
    return order


def _fake_urlopen_response(json_bytes):
    response = MagicMock()
    response.read.return_value = json_bytes
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


# --- geocode() (Nominatim always mocked - never call the real API from tests) ---

def test_geocode_valid_address_returns_coordinates(db):
    with patch('app.geocoding.urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value = _fake_urlopen_response(b'[{"lat": "-38.1234", "lon": "-72.5678"}]')
        result = geocode('Arturo Prat 123, Angol')

    assert result == (-38.1234, -72.5678)


def test_geocode_address_not_found_returns_none(db):
    with patch('app.geocoding.urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value = _fake_urlopen_response(b'[]')
        result = geocode('direccion que no existe en ningun lado 999999')

    assert result is None


def test_geocode_network_failure_returns_none_not_raises(db):
    with patch('app.geocoding.urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError('timed out')
        result = geocode('cualquier direccion')

    assert result is None


def test_geocode_empty_address_returns_none_without_calling_nominatim(db):
    with patch('app.geocoding.urllib.request.urlopen') as mock_urlopen:
        result = geocode('')

    assert result is None
    mock_urlopen.assert_not_called()


# --- GET /admin/agenda/cercania ---

def test_cercania_ranks_by_distance_ascending(client, db):
    _register_owner(client)
    product = _create_product(db)
    far = _create_order(db, product, customer_name='Lejos', daily_number=1, latitude=-38.5, longitude=-73.0)
    near = _create_order(db, product, customer_name='Cerca', daily_number=2, latitude=-38.15, longitude=-72.61)

    with patch.object(catalog_routes, 'geocode', return_value=(-38.15, -72.60)):
        resp = client.get('/admin/agenda/cercania?direccion=Centro')

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    names = [r['customerName'] for r in data['results']]
    assert names == ['Cerca', 'Lejos']
    assert data['results'][0]['distanceKm'] < data['results'][1]['distanceKm']


def test_cercania_order_without_coordinates_listed_separately_not_lost(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_order(db, product, customer_name='ConUbicacion', daily_number=1,
                   latitude=-38.15, longitude=-72.61)
    _create_order(db, product, customer_name='SinUbicacion', daily_number=2,
                   latitude=None, longitude=None)

    with patch.object(catalog_routes, 'geocode', return_value=(-38.15, -72.60)):
        resp = client.get('/admin/agenda/cercania?direccion=Centro')

    data = resp.get_json()
    assert data['ok'] is True
    assert len(data['results']) == 1
    assert data['results'][0]['customerName'] == 'ConUbicacion'
    assert len(data['withoutLocation']) == 1
    assert data['withoutLocation'][0]['customerName'] == 'SinUbicacion'


def test_cercania_excludes_retiro_orders(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_order(db, product, delivery_mode='envio', customer_name='Despacho',
                   daily_number=1, latitude=-38.15, longitude=-72.61)
    _create_order(db, product, delivery_mode='retira', customer_name='Retiro', daily_number=2)

    with patch.object(catalog_routes, 'geocode', return_value=(-38.15, -72.60)):
        resp = client.get('/admin/agenda/cercania?direccion=Centro')

    data = resp.get_json()
    all_names = [r['customerName'] for r in data['results']] + [r['customerName'] for r in data['withoutLocation']]
    assert 'Despacho' in all_names
    assert 'Retiro' not in all_names


def test_cercania_excludes_pending_and_cancelled_orders(client, db):
    _register_owner(client)
    product = _create_product(db)
    _create_order(db, product, status='Confirmed', customer_name='Confirmado',
                   daily_number=1, latitude=-38.15, longitude=-72.61)
    _create_order(db, product, status='Pending', customer_name='Pendiente',
                   latitude=-38.15, longitude=-72.61)
    _create_order(db, product, status='Cancelled', customer_name='Cancelado',
                   latitude=-38.15, longitude=-72.61)

    with patch.object(catalog_routes, 'geocode', return_value=(-38.15, -72.60)):
        resp = client.get('/admin/agenda/cercania?direccion=Centro')

    data = resp.get_json()
    names = [r['customerName'] for r in data['results']]
    assert names == ['Confirmado']


def test_cercania_address_not_found_returns_clear_message_not_500(client, db):
    _register_owner(client)

    with patch.object(catalog_routes, 'geocode', return_value=None):
        resp = client.get('/admin/agenda/cercania?direccion=direccion+inexistente')

    assert resp.status_code == 400
    data = resp.get_json()
    assert data['ok'] is False
    assert 'message' in data


def test_cercania_missing_address_param_returns_400_not_500(client, db):
    _register_owner(client)

    resp = client.get('/admin/agenda/cercania')

    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False
