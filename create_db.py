from app import create_app, db
from app.models import Product, Category, Subcategory, Order, OrderItem

app = create_app()
with app.app_context():
    db.create_all()

    if Product.query.count() == 0:
        cafe = Category(name='Bebidas')
        db.session.add(cafe)
        db.session.flush()
        sub = Subcategory(name='Fríos', category_id=cafe.id)
        db.session.add(sub)
        db.session.flush()
        products = [
            {'name': 'Jugo natural', 'description': 'Naranja, limón y jengibre.', 'price': 4200, 'category_id': cafe.id, 'subcategory_id': sub.id},
            {'name': 'Café americano', 'description': 'Café filtrado, suave y aromático.', 'price': 3200, 'category_id': cafe.id, 'subcategory_id': sub.id},
            {'name': 'Té helado', 'description': 'Té con limón y menta fresca.', 'price': 3800, 'category_id': cafe.id, 'subcategory_id': sub.id},
        ]
        for item in products:
            db.session.add(Product(**item))
    db.session.commit()
