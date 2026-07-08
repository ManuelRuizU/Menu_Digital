from app.models import BundlePromo, Category, Coupon, Order, OrderItem, Product, User


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _create_product(db, price=1000, name='Producto'):
    category = Category.query.first()
    if category is None:
        category = Category(name='Categoria')
        db.session.add(category)
        db.session.commit()
    product = Product(name=name, description='Test', price=price, category_id=category.id)
    db.session.add(product)
    db.session.commit()
    return product


# --- the four blocking reasons ---

def test_delete_blocked_when_product_has_orders(client, db):
    _register_owner(client)
    product = _create_product(db)
    order = Order(customer_name='Cliente', phone='56911112222', delivery_mode='retira',
                   payment_method='efectivo', total_price=1000, status='Pending')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=1, price=1000))
    db.session.commit()

    resp = client.post(f'/admin/products/{product.id}/delete', follow_redirects=True)

    assert b'tiene pedidos asociados' in resp.data
    assert Product.query.get(product.id) is not None


def test_delete_blocked_when_product_in_coupon(client, db):
    _register_owner(client)
    product = _create_product(db)
    coupon = Coupon(code='PRIMERACOMPRA', discount_percent=10, scope='products', is_active=True)
    coupon.products = [product]
    db.session.add(coupon)
    db.session.commit()

    resp = client.post(f'/admin/products/{product.id}/delete', follow_redirects=True)

    assert 'PRIMERACOMPRA'.encode() in resp.data
    assert Product.query.get(product.id) is not None


def test_delete_blocked_when_product_in_bundle_promo(client, db):
    _register_owner(client)
    product = _create_product(db)
    promo = BundlePromo(label='3x2 Rolls', buy_quantity=3, pay_quantity=2, is_active=True)
    promo.products = [product]
    db.session.add(promo)
    db.session.commit()

    resp = client.post(f'/admin/products/{product.id}/delete', follow_redirects=True)

    assert '3x2 Rolls'.encode() in resp.data
    assert Product.query.get(product.id) is not None


def test_delete_blocked_when_product_is_gift(client, db):
    _register_owner(client)
    product = _create_product(db)
    owner = User.query.filter_by(is_owner=True).first()
    owner.gift_threshold_amount = 30000
    owner.gift_product_id = product.id
    db.session.commit()

    resp = client.post(f'/admin/products/{product.id}/delete', follow_redirects=True)

    assert 'regalo'.encode() in resp.data
    assert Product.query.get(product.id) is not None


def test_delete_flash_combines_multiple_reasons(client, db):
    _register_owner(client)
    product = _create_product(db)
    coupon = Coupon(code='PRIMERACOMPRA', discount_percent=10, scope='products', is_active=True)
    coupon.products = [product]
    promo = BundlePromo(label='3x2 Rolls', buy_quantity=3, pay_quantity=2, is_active=True)
    promo.products = [product]
    db.session.add_all([coupon, promo])
    db.session.commit()

    resp = client.post(f'/admin/products/{product.id}/delete', follow_redirects=True)

    assert 'PRIMERACOMPRA'.encode() in resp.data
    assert '3x2 Rolls'.encode() in resp.data
    assert Product.query.get(product.id) is not None


# --- the "nothing blocks it" case ---

def test_delete_succeeds_when_nothing_references_product(client, db):
    _register_owner(client)
    product = _create_product(db)

    resp = client.post(f'/admin/products/{product.id}/delete', follow_redirects=True)

    assert 'Producto eliminado'.encode() in resp.data
    assert Product.query.get(product.id) is None
