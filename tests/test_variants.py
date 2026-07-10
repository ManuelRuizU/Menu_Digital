from app.models import Category, Product, ProductOption, ProductOptionGroup


def _create_pizza(db):
    category = Category(name='Pizzas')
    db.session.add(category)
    db.session.commit()
    product = Product(name='Pizza', description='Test', price=6000, category_id=category.id)
    db.session.add(product)
    db.session.commit()

    size_group = ProductOptionGroup(product_id=product.id, name='Tamaño', required=True, multi_select=False)
    extras_group = ProductOptionGroup(product_id=product.id, name='Extras', required=False, multi_select=True)
    db.session.add_all([size_group, extras_group])
    db.session.commit()

    individual = ProductOption(group_id=size_group.id, name='Individual', price_delta=0)
    familiar = ProductOption(group_id=size_group.id, name='Familiar', price_delta=2500)
    cheese = ProductOption(group_id=extras_group.id, name='Extra queso', price_delta=1000)
    bacon = ProductOption(group_id=extras_group.id, name='Tocino', price_delta=1500)
    db.session.add_all([individual, familiar, cheese, bacon])
    db.session.commit()

    return product, size_group, extras_group, individual, familiar, cheese, bacon


def _order_payload(order_payload, product_id, options, phone='56911112222'):
    return order_payload(items=[{'id': product_id, 'quantity': 1, 'options': options}], phone=phone)


def test_order_computes_price_with_selected_options(client, db, order_payload):
    product, *_ , familiar, cheese, bacon = _create_pizza(db)

    resp = client.post('/api/orders', json=_order_payload(order_payload, product.id, [familiar.id, cheese.id]))
    assert resp.status_code == 200

    from app.models import Order, OrderItem
    order = Order.query.order_by(Order.id.desc()).first()
    item = OrderItem.query.filter_by(order_id=order.id).first()
    assert item.price == 6000 + 2500 + 1000  # base + Familiar + Extra queso
    assert {o.name for o in item.selected_options} == {'Familiar', 'Extra queso'}


def test_order_rejects_missing_required_group(client, db, order_payload):
    product, *_ = _create_pizza(db)

    resp = client.post('/api/orders', json=_order_payload(order_payload, product.id, []))
    assert resp.status_code == 400
    assert 'Tamaño' in resp.get_json()['message']


def test_order_rejects_multiple_choices_in_single_select_group(client, db, order_payload):
    product, _, _, individual, familiar, *_ = _create_pizza(db)

    resp = client.post('/api/orders', json=_order_payload(order_payload, product.id, [individual.id, familiar.id]))
    assert resp.status_code == 400
    assert 'Tamaño' in resp.get_json()['message']


def test_order_allows_multiple_choices_in_multi_select_group(client, db, order_payload):
    product, _, _, individual, _, cheese, bacon = _create_pizza(db)

    resp = client.post('/api/orders',
                        json=_order_payload(order_payload, product.id, [individual.id, cheese.id, bacon.id]))
    assert resp.status_code == 200

    from app.models import Order, OrderItem
    order = Order.query.order_by(Order.id.desc()).first()
    item = OrderItem.query.filter_by(order_id=order.id).first()
    assert item.price == 6000 + 0 + 1000 + 1500


def test_order_rejects_option_from_another_product(client, db, order_payload):
    product, *_ , familiar, cheese, bacon = _create_pizza(db)
    other = Product(name='Bebida', description='Test', price=1000, category_id=product.category_id)
    db.session.add(other)
    db.session.commit()

    # Trying to use the pizza's "Familiar" option against a product with no option groups at all.
    resp = client.post('/api/orders', json=_order_payload(order_payload, other.id, [familiar.id]))
    assert resp.status_code == 400


def test_order_rejects_nonexistent_option_id(client, db, order_payload):
    product, *_ = _create_pizza(db)

    resp = client.post('/api/orders', json=_order_payload(order_payload, product.id, [999999]))
    assert resp.status_code == 400
