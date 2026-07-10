import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db as _db


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')

    application = create_app({
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SESSION_COOKIE_SECURE': False,
        'SECRET_KEY': 'test-secret-key',
    })

    yield application

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    with app.app_context():
        yield _db


@pytest.fixture
def order_payload():
    """Fábrica de payloads válidos para POST /api/orders. Centraliza los defaults
    (incluido requestedTime) en un solo lugar - el próximo campo obligatorio se
    agrega acá una vez, no en cada test que arma un pedido para probar otra cosa."""
    def _build(**overrides):
        payload = {
            'items': [],
            'customerName': 'Cliente',
            'phone': '56911112222',
            'deliveryMode': 'retira',
            'paymentMethod': 'efectivo',
            'requestedTime': '19:00',
        }
        payload.update(overrides)
        return payload
    return _build
