# restore_backup.py
# Herramienta de recuperación: restaura un respaldo .json (el que se manda por
# correo en instalaciones que no usan SQLite - ver app/backup.py) sobre la base de
# datos actual. Uso de emergencia, no un import de rutina - borra y reemplaza el
# contenido de cada tabla que venga en el respaldo.
import json
import sys

from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Uso: python restore_backup.py respaldo_2026-01-01.json')

    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        dump = json.load(f)

    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        is_postgres = db.engine.url.get_backend_name().startswith('postgres')

        with db.engine.begin() as conn:
            # Postgres enforces foreign keys as each statement runs - turning this off
            # for the session lets us delete/insert tables in any order, since we're
            # about to reload every table from the same consistent snapshot anyway.
            if is_postgres:
                conn.execute(text('SET session_replication_role = replica'))

            for table_name, rows in dump.items():
                if table_name not in existing_tables:
                    print(f'Aviso: la tabla "{table_name}" ya no existe, se omite.')
                    continue
                conn.execute(text(f'DELETE FROM "{table_name}"'))
                if not rows:
                    continue
                columns = rows[0].keys()
                col_list = ', '.join(f'"{c}"' for c in columns)
                placeholders = ', '.join(f':{c}' for c in columns)
                conn.execute(text(f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})'), rows)
                print(f'{table_name}: {len(rows)} filas restauradas')

            if is_postgres:
                conn.execute(text('SET session_replication_role = DEFAULT'))

    print('Respaldo restaurado.')


if __name__ == '__main__':
    main()
