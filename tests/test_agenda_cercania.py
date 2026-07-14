import urllib.error
from unittest.mock import MagicMock, patch

from app.catalog import routes as catalog_routes
from app.geocoding import geocode
from app.models import Category, Order, OrderItem, Product, User


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _set_owner_location(db, lat, lng):
    owner = User.query.filter_by(is_owner=True).first()
    owner.latitude = lat
    owner.longitude = lng
    db.session.commit()


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
    # No owner location is set here - detour math is unavailable and this falls back
    # to plain point-to-point distance, same ranking the endpoint always used to give.
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
    assert data['results'][0]['detourKm'] < data['results'][1]['detourKm']


# --- detour-based ranking (replaces plain point-to-point distance) ---
# Shared geometry for all detour tests: LOCAL is the courier's real starting point.
# FAR sits straight south of LOCAL; NUEVO_EN_CAMINO sits on that same line, a third of
# the way there ("on the way" to FAR); NUEVO_OPUESTO sits the same distance from LOCAL
# but in the opposite direction (north instead of south).
LOCAL = (-38.00, -72.00)
FAR = (-38.30, -72.00)
NUEVO_EN_CAMINO = (-38.10, -72.00)
NUEVO_OPUESTO = (-37.90, -72.00)
# CLOSE sits right next to NUEVO_EN_CAMINO in a straight line (small point-to-point
# distance) but off to the side of the LOCAL->FAR route, not on it.
CLOSE = (-38.10, -72.05)


def test_cercania_detour_low_for_order_on_the_way_despite_large_point_to_point_distance(client, db):
    _register_owner(client)
    _set_owner_location(db, *LOCAL)
    product = _create_product(db)
    far = _create_order(db, product, customer_name='Far', daily_number=1, latitude=FAR[0], longitude=FAR[1])

    with patch.object(catalog_routes, 'geocode', return_value=NUEVO_EN_CAMINO):
        resp = client.get('/admin/agenda/cercania?direccion=Centro')

    data = resp.get_json()
    assert data['ok'] is True
    assert data['detourAvailable'] is True
    result = data['results'][0]
    assert result['customerName'] == 'Far'
    # Straight-line distance from the new address to Far is ~22 km (large), but Far is
    # essentially on the way there - the detour must be tiny by comparison.
    assert result['detourKm'] < 1
    point_to_point = catalog_routes._haversine_km(*NUEVO_EN_CAMINO, *FAR)
    assert point_to_point > 20
    assert result['detourKm'] < point_to_point / 10


def test_cercania_detour_high_for_order_in_opposite_direction(client, db):
    _register_owner(client)
    _set_owner_location(db, *LOCAL)
    product = _create_product(db)
    far = _create_order(db, product, customer_name='Far', daily_number=1, latitude=FAR[0], longitude=FAR[1])

    with patch.object(catalog_routes, 'geocode', return_value=NUEVO_OPUESTO):
        resp = client.get('/admin/agenda/cercania?direccion=Centro')

    data = resp.get_json()
    assert data['ok'] is True
    result = data['results'][0]
    assert result['customerName'] == 'Far'
    # NUEVO_OPUESTO is the same raw distance from LOCAL as NUEVO_EN_CAMINO was, but on
    # the opposite side - bundling it in means backtracking, so the detour is high.
    assert result['detourKm'] > 15


def test_cercania_orders_by_detour_not_by_point_to_point_distance(client, db):
    _register_owner(client)
    _set_owner_location(db, *LOCAL)
    product = _create_product(db)
    far = _create_order(db, product, customer_name='Far', daily_number=1, latitude=FAR[0], longitude=FAR[1])
    close = _create_order(db, product, customer_name='Close', daily_number=2, latitude=CLOSE[0], longitude=CLOSE[1])

    with patch.object(catalog_routes, 'geocode', return_value=NUEVO_EN_CAMINO):
        resp = client.get('/admin/agenda/cercania?direccion=Centro')

    data = resp.get_json()
    # Point-to-point, Close (~4.4 km) is nearer than Far (~22 km) - the OLD metric
    # would rank Close first. Far is on the route and barely detours, so by detour
    # it must come first instead - the ranking flips.
    point_to_point_far = catalog_routes._haversine_km(*NUEVO_EN_CAMINO, *FAR)
    point_to_point_close = catalog_routes._haversine_km(*NUEVO_EN_CAMINO, *CLOSE)
    assert point_to_point_close < point_to_point_far  # confirms the old metric would disagree

    names = [r['customerName'] for r in data['results']]
    assert names == ['Far', 'Close']
    assert data['results'][0]['detourKm'] < data['results'][1]['detourKm']


def test_cercania_falls_back_to_point_to_point_when_owner_has_no_location(client, db):
    # Owner location is deliberately never set - the pin on the business profile map
    # is optional and plenty of real installs never touch it.
    _register_owner(client)
    product = _create_product(db)
    far = _create_order(db, product, customer_name='Lejos', daily_number=1, latitude=-38.5, longitude=-73.0)
    near = _create_order(db, product, customer_name='Cerca', daily_number=2, latitude=-38.15, longitude=-72.61)

    with patch.object(catalog_routes, 'geocode', return_value=(-38.15, -72.60)):
        resp = client.get('/admin/agenda/cercania?direccion=Centro')

    assert resp.status_code == 200  # never a 500, even without owner coordinates
    data = resp.get_json()
    assert data['ok'] is True
    assert data['detourAvailable'] is False
    assert data['message'] == catalog_routes.NO_OWNER_LOCATION_MESSAGE
    # Falls back to the old point-to-point ranking, not broken/empty.
    names = [r['customerName'] for r in data['results']]
    assert names == ['Cerca', 'Lejos']


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
