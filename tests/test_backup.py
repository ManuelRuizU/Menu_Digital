import json

from app.backup import _dump_database_bytes
from app.models import Category


def test_dump_sqlite_returns_raw_file_bytes(app, db):
    with app.app_context():
        data, extension = _dump_database_bytes()
    assert extension == 'db'
    assert data  # the temp sqlite file has at least the schema written to it


def test_dump_non_sqlite_returns_json_of_all_tables(app, db):
    db.session.add(Category(name='Categoria de prueba'))
    db.session.commit()

    with app.app_context():
        app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://fake/for-this-test-only'
        data, extension = _dump_database_bytes()

    assert extension == 'json'
    dump = json.loads(data)
    assert 'category' in dump
    assert any(row['name'] == 'Categoria de prueba' for row in dump['category'])
