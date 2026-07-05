# my_menu/create_superuser.py
# Herramienta de recuperación: crea o resetea al dueño de este menú.
# En condiciones normales, el dueño se crea una sola vez a través de /register.
import getpass
import os

from app import create_app, db
from app.models import User

USERNAME = os.environ.get('SUPERUSER_USERNAME', 'admin')
EMAIL = os.environ.get('SUPERUSER_EMAIL', 'admin@example.com')

app = create_app()
with app.app_context():
    password = os.environ.get('SUPERUSER_PASSWORD')
    if not password:
        password = getpass.getpass(f'Contraseña para {EMAIL}: ')
    if not password:
        raise SystemExit('Se requiere una contraseña.')

    superuser = User.query.filter((User.username == USERNAME) | (User.email == EMAIL)).first()
    if superuser is None:
        superuser = User(username=USERNAME, email=EMAIL, is_admin=True, is_owner=True)
        db.session.add(superuser)

    superuser.username = USERNAME
    superuser.email = EMAIL
    superuser.is_admin = True
    superuser.is_owner = True
    superuser.set_password(password)
    db.session.commit()
    print("Superusuario listo para usar")


