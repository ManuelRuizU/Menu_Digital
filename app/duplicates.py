# app/duplicates.py
"""Catalog names that are the same under normalize_name - what the panel now refuses to
create, but data saved before that rule can still hold. `flask check-duplicates` lists
them, to clean up before deploying the rule (the panel would otherwise refuse to save
either of the two rows until one is renamed)."""
from collections import defaultdict

import click

from app.models import Category, Product, Subcategory
from app.utils import normalize_name


def _groups(rows, key):
    by_key = defaultdict(list)
    for row in rows:
        by_key[key(row)].append(row)
    return [sorted(group, key=lambda row: row.id) for group in by_key.values() if len(group) > 1]


def find_duplicates():
    """{'categories': [[Category, ...], ...], 'subcategories': [...], 'products': [...]}, each
    inner list one group of rows sharing a normalized name within the same scope: global
    for categories, the category for subcategories and products (active or not)."""
    return {
        'categories': _groups(Category.query.all(), lambda c: normalize_name(c.name)),
        'subcategories': _groups(Subcategory.query.all(), lambda s: (s.category_id, normalize_name(s.name))),
        'products': _groups(Product.query.all(), lambda p: (p.category_id, normalize_name(p.name))),
    }


def _describe(kind, row):
    if kind == 'categories':
        return f'#{row.id} "{row.name}"'
    where = f' en "{row.category.name}"' if row.category else ''
    extra = '' if kind != 'products' or row.is_active else ' (inactivo)'
    return f'#{row.id} "{row.name}"{where}{extra}'


TITLES = {'categories': 'Categorías', 'subcategories': 'Subcategorías', 'products': 'Productos'}


@click.command('check-duplicates')
def check_duplicates_command():
    """Lista categorías, subcategorías y productos con nombres duplicados (sin distinguir
    mayúsculas, espacios ni tildes). Sale con código 1 si encuentra alguno."""
    found = find_duplicates()
    total = sum(len(groups) for groups in found.values())
    for kind, groups in found.items():
        click.echo(f'{TITLES[kind]}: {len(groups) or "sin"} grupo{"s" if len(groups) != 1 else ""} duplicado'
                   f'{"s" if len(groups) != 1 else ""}')
        for group in groups:
            click.echo('  - ' + ' = '.join(_describe(kind, row) for row in group))
    if total:
        click.echo(f'\n{total} grupo(s) para limpiar: renombra o elimina desde el panel antes del deploy.')
        raise SystemExit(1)
    click.echo('\nSin duplicados.')
