import json

from app.models import Category, Order, OrderItem, Product, User


def _register_owner(client):
    client.post('/register', data={
        'username': 'dueno', 'email': 'dueno@test.com', 'password': 'secret123',
    })


def _create_product(db, stock_quantity=None, price=1000):
    category = Category(name='Bebidas')
    db.session.add(category)
    db.session.commit()
    product = Product(name='Bebida', description='Test', price=price,
                       category_id=category.id, stock_quantity=stock_quantity)
    db.session.add(product)
    db.session.commit()
    return product


def _create_order_with_item(db, product, quantity=1):
    order = Order(customer_name='Cliente', phone='56911112222', delivery_mode='retira',
                  payment_method='efectivo', total_price=product.price * quantity, status='Pending')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              quantity=quantity, price=product.price))
    db.session.commit()
    return order


# --- stock decrement on public checkout (/api/orders) ---

def test_create_order_decrements_stock(client, db):
    product = _create_product(db, stock_quantity=5)

    resp = client.post('/api/orders', json={
        'items': [{'id': product.id, 'quantity': 2}],
        'customerName': 'Cliente', 'phone': '56911112222',
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True

    db.session.refresh(product)
    assert product.stock_quantity == 3
    assert product.sold_out is False


def test_create_order_marks_sold_out_at_zero_stock(client, db):
    product = _create_product(db, stock_quantity=2)

    resp = client.post('/api/orders', json={
        'items': [{'id': product.id, 'quantity': 2}],
        'customerName': 'Cliente', 'phone': '56911112222',
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    assert resp.status_code == 200

    db.session.refresh(product)
    assert product.stock_quantity == 0
    assert product.sold_out is True


def test_create_order_rejects_insufficient_stock(client, db):
    product = _create_product(db, stock_quantity=1)

    resp = client.post('/api/orders', json={
        'items': [{'id': product.id, 'quantity': 5}],
        'customerName': 'Cliente', 'phone': '56911112222',
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False

    db.session.refresh(product)
    assert product.stock_quantity == 1  # unchanged - the rejected order must not touch stock


def test_create_order_with_unlimited_stock_product(client, db):
    product = _create_product(db, stock_quantity=None)

    resp = client.post('/api/orders', json={
        'items': [{'id': product.id, 'quantity': 100}],
        'customerName': 'Cliente', 'phone': '56911112222',
        'deliveryMode': 'retira', 'paymentMethod': 'efectivo',
    })
    assert resp.status_code == 200

    db.session.refresh(product)
    assert product.stock_quantity is None
    assert product.sold_out is False


# --- stock decrement/restore via the admin order-item editor ---

def test_add_order_item_decrements_stock(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=5)
    # _create_order_with_item inserts the order directly, bypassing checkout - so
    # stock still reflects only what add_order_item itself is about to decrement.
    order = _create_order_with_item(db, product, quantity=1)

    resp = client.post(f'/admin/orders/{order.id}/items/add', data={
        'product_id': product.id, 'quantity': 2,
    })
    assert resp.status_code == 302

    db.session.refresh(product)
    assert product.stock_quantity == 3  # 5 - 2 (added)


def test_remove_order_item_restores_stock(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=5)
    # Simulate stock already reduced by the initial item (as if it came through checkout).
    product.stock_quantity = 3
    order = _create_order_with_item(db, product, quantity=2)
    # A second item so removal is allowed (an order must keep at least one item).
    other_product = _create_product(db, stock_quantity=None, price=500)
    db.session.add(OrderItem(order_id=order.id, product_id=other_product.id, product_name=other_product.name,
                              quantity=1, price=500))
    db.session.commit()

    item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
    resp = client.post(f'/admin/orders/{order.id}/items/{item.id}/remove')
    assert resp.status_code == 302

    db.session.refresh(product)
    assert product.stock_quantity == 5  # 3 + 2 restored


def test_remove_order_item_clears_sold_out_when_restored(client, db):
    _register_owner(client)
    product = _create_product(db, stock_quantity=0)
    product.sold_out = True
    order = _create_order_with_item(db, product, quantity=2)
    other_product = _create_product(db, stock_quantity=None, price=500)
    db.session.add(OrderItem(order_id=order.id, product_id=other_product.id, product_name=other_product.name,
                              quantity=1, price=500))
    db.session.commit()

    item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
    client.post(f'/admin/orders/{order.id}/items/{item.id}/remove')

    db.session.refresh(product)
    assert product.stock_quantity == 2
    assert product.sold_out is False


# --- order total recalculation ---

def test_add_order_item_recalculates_total(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, stock_quantity=None)
    order = _create_order_with_item(db, product, quantity=1)  # total starts at 1000
    other = _create_product(db, price=500, stock_quantity=None)

    client.post(f'/admin/orders/{order.id}/items/add', data={'product_id': other.id, 'quantity': 3})

    db.session.refresh(order)
    assert order.total_price == 1000 + 500 * 3


def test_remove_order_item_recalculates_total(client, db):
    _register_owner(client)
    product = _create_product(db, price=1000, stock_quantity=None)
    other = _create_product(db, price=500, stock_quantity=None)
    order = _create_order_with_item(db, product, quantity=1)
    db.session.add(OrderItem(order_id=order.id, product_id=other.id, product_name=other.name,
                              quantity=2, price=500))
    order.total_price = 1000 + 500 * 2
    db.session.commit()

    item = OrderItem.query.filter_by(order_id=order.id, product_id=other.id).first()
    client.post(f'/admin/orders/{order.id}/items/{item.id}/remove')

    db.session.refresh(order)
    assert order.total_price == 1000
