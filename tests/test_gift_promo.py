from app.models import Category, Order, OrderItem, Product, User


PHONE = '56911112222'


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _create_product(db, price=1000, name='Producto', stock_quantity=None):
    category = Category.query.first()
    if category is None:
        category = Category(name='Categoria')
        db.session.add(category)
        db.session.commit()
    product = Product(name=name, description='Test', price=price, category_id=category.id,
                       stock_quantity=stock_quantity)
    db.session.add(product)
    db.session.commit()
    return product


def _set_gift(db, threshold, gift_product):
    owner = User.query.filter_by(is_owner=True).first()
    owner.gift_threshold_amount = threshold
    owner.gift_product_id = gift_product.id
    db.session.commit()
    return owner


def test_gift_added_when_total_reaches_threshold(client, db):
    _register_owner(client)
    main_product = _create_product(db, price=10000, name='Principal')
    gift = _create_product(db, price=2000, name='Cafe', stock_quantity=5)
    _set_gift(db, threshold=8000, gift_product=gift)

    resp = client.post('/api/orders', json={
        'items': [{'id': main_product.id, 'quantity': 1}],
        'customerName': 'Cliente', 'phone': PHONE,
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    order = Order.query.order_by(Order.id.desc()).first()
    gift_item = OrderItem.query.filter_by(order_id=order.id, product_id=gift.id).first()
    assert gift_item is not None
    assert gift_item.price == 0
    assert order.total_price == 10000  # gift doesn't change the total

    db.session.refresh(gift)
    assert gift.stock_quantity == 4  # decremented like any dispatched item


def test_no_gift_when_below_threshold(client, db):
    _register_owner(client)
    main_product = _create_product(db, price=5000, name='Chico')
    gift = _create_product(db, price=2000, name='Cafe2', stock_quantity=5)
    _set_gift(db, threshold=8000, gift_product=gift)

    resp = client.post('/api/orders', json={
        'items': [{'id': main_product.id, 'quantity': 1}],
        'customerName': 'Cliente', 'phone': PHONE,
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    order = Order.query.order_by(Order.id.desc()).first()
    gift_item = OrderItem.query.filter_by(order_id=order.id, product_id=gift.id).first()
    assert gift_item is None


def test_no_gift_when_out_of_stock(client, db):
    _register_owner(client)
    main_product = _create_product(db, price=10000, name='Principal2')
    gift = _create_product(db, price=2000, name='Cafe3', stock_quantity=0)
    gift.sold_out = True
    db.session.commit()
    _set_gift(db, threshold=8000, gift_product=gift)

    resp = client.post('/api/orders', json={
        'items': [{'id': main_product.id, 'quantity': 1}],
        'customerName': 'Cliente', 'phone': PHONE,
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    order = Order.query.order_by(Order.id.desc()).first()
    gift_item = OrderItem.query.filter_by(order_id=order.id, product_id=gift.id).first()
    assert gift_item is None


# --- /admin/promotions/gift form: cross-validation between threshold and product ---

def test_update_gift_promo_rejects_threshold_without_product(client, db):
    _register_owner(client)

    resp = client.post('/admin/promotions/gift', data={
        'gift_threshold_amount': '30000',
    }, follow_redirects=True)

    assert 'Para activar el regalo'.encode() in resp.data
    owner = User.query.filter_by(is_owner=True).first()
    assert owner.gift_threshold_amount is None
    assert owner.gift_product_id is None


def test_update_gift_promo_rejects_product_without_threshold(client, db):
    _register_owner(client)
    gift = _create_product(db, price=2000, name='Cafe4')

    resp = client.post('/admin/promotions/gift', data={
        'gift_product_id': str(gift.id),
    }, follow_redirects=True)

    assert 'Para activar el regalo'.encode() in resp.data
    owner = User.query.filter_by(is_owner=True).first()
    assert owner.gift_threshold_amount is None
    assert owner.gift_product_id is None


def test_update_gift_promo_saves_when_both_present(client, db):
    _register_owner(client)
    gift = _create_product(db, price=2000, name='Cafe5')

    resp = client.post('/admin/promotions/gift', data={
        'gift_threshold_amount': '30000',
        'gift_product_id': str(gift.id),
    }, follow_redirects=True)

    assert 'Regalo por compra mínima actualizado'.encode() in resp.data
    owner = User.query.filter_by(is_owner=True).first()
    assert owner.gift_threshold_amount == 30000
    assert owner.gift_product_id == gift.id


def test_update_gift_promo_saves_when_both_empty_clears_it(client, db):
    _register_owner(client)
    gift = _create_product(db, price=2000, name='Cafe6')
    _set_gift(db, threshold=30000, gift_product=gift)

    resp = client.post('/admin/promotions/gift', data={}, follow_redirects=True)

    assert 'Regalo por compra mínima actualizado'.encode() in resp.data
    owner = User.query.filter_by(is_owner=True).first()
    assert owner.gift_threshold_amount is None
    assert owner.gift_product_id is None
