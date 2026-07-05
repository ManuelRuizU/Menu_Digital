from app.main.routes import compute_shipping_cost, get_owner, is_within_business_hours
from app.models import DeliveryRadiusTier, DeliveryZone, User


# --- is_within_business_hours ---

def test_no_hours_configured_always_allowed():
    assert is_within_business_hours('03:00', None, None) is True


def test_time_inside_normal_range():
    assert is_within_business_hours('13:00', '12:00', '22:00') is True


def test_time_outside_normal_range():
    assert is_within_business_hours('10:00', '12:00', '22:00') is False


def test_time_at_exact_boundaries():
    assert is_within_business_hours('12:00', '12:00', '22:00') is True
    assert is_within_business_hours('22:00', '12:00', '22:00') is True


def test_range_crossing_midnight_inside():
    # Open 18:00 - 02:00: both 23:00 and 01:00 should be inside.
    assert is_within_business_hours('23:00', '18:00', '02:00') is True
    assert is_within_business_hours('01:00', '18:00', '02:00') is True


def test_range_crossing_midnight_outside():
    assert is_within_business_hours('10:00', '18:00', '02:00') is False


# --- get_owner ---

def test_get_owner_returns_owner_not_staff(db):
    # Staff inserted first (lower id) on purpose: filtering by is_admin alone would
    # return this row first in SQLite's default ordering, masking the bug this guards.
    staff = User(username='empleado', email='empleado@test.com', password_hash='x',
                 is_admin=True, is_owner=False)
    db.session.add(staff)
    db.session.commit()

    owner = User(username='dueno', email='dueno@test.com', password_hash='x',
                 is_admin=True, is_owner=True, business_name='Negocio Real')
    db.session.add(owner)
    db.session.commit()

    found = get_owner()
    assert found is not None
    assert found.is_owner is True
    assert found.business_name == 'Negocio Real'


def test_get_owner_none_when_no_users(db):
    assert get_owner() is None


# --- compute_shipping_cost ---

def test_shipping_cost_no_configuration(db):
    owner = User(username='dueno', email='dueno@test.com', password_hash='x',
                 is_admin=True, is_owner=True, latitude=-37.8, longitude=-72.7)
    db.session.add(owner)
    db.session.commit()

    cost, covered = compute_shipping_cost(-37.8, -72.7)
    assert covered is False
    assert cost is None


def test_shipping_cost_within_radius_tier(db):
    owner = User(username='dueno', email='dueno@test.com', password_hash='x',
                 is_admin=True, is_owner=True, latitude=-37.8, longitude=-72.7)
    db.session.add(owner)
    db.session.add(DeliveryRadiusTier(min_km=0, max_km=3, price=1500))
    db.session.add(DeliveryRadiusTier(min_km=3, max_km=6, price=2500))
    db.session.commit()

    # ~0.5km north of the business - should land in the first tier.
    cost, covered = compute_shipping_cost(-37.805, -72.7)
    assert covered is True
    assert cost == 1500


def test_shipping_cost_outside_all_tiers(db):
    owner = User(username='dueno', email='dueno@test.com', password_hash='x',
                 is_admin=True, is_owner=True, latitude=-37.8, longitude=-72.7)
    db.session.add(owner)
    db.session.add(DeliveryRadiusTier(min_km=0, max_km=3, price=1500))
    db.session.commit()

    # Far enough away (~1 degree ~ 111km) to fall outside the only configured tier.
    cost, covered = compute_shipping_cost(-38.8, -72.7)
    assert covered is False
    assert cost is None


def test_shipping_cost_zone_takes_precedence_over_radius(db):
    owner = User(username='dueno', email='dueno@test.com', password_hash='x',
                 is_admin=True, is_owner=True, latitude=-37.8, longitude=-72.7)
    db.session.add(owner)
    db.session.add(DeliveryRadiusTier(min_km=0, max_km=10, price=1500))
    # A square polygon around the business's own point, with its own fixed price.
    geojson = '{"type": "Polygon", "coordinates": [[[-72.71, -37.81], [-72.69, -37.81], [-72.69, -37.79], [-72.71, -37.79], [-72.71, -37.81]]]}'
    db.session.add(DeliveryZone(name='Centro', price=999, geojson=geojson))
    db.session.commit()

    cost, covered = compute_shipping_cost(-37.8, -72.7)
    assert covered is True
    assert cost == 999
