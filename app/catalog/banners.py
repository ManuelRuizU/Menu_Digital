# app/catalog/banners.py
"""Panel "Banners": the slides the owner uploads for the big carousel at the top of the
menu (app/storefront.py renders them). Everything the form sends is re-checked here."""
import secrets
from datetime import datetime

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app import db
from app.catalog import catalog
from app.decorators import owner_required
from app.models import HERO_TARGET_TYPES, MAX_ACTIVE_HERO_BANNERS, Category, HeroBanner, Product
from app.uploads import delete_image, save_image, save_image_with_half
from app.utils import clean_name

TITLE_MAX, TEXT_MAX, BUTTON_MAX = 80, 200, 30
DESKTOP_MAX_DIMENSION = 1920
MOBILE_MAX_DIMENSION = 1080
TOO_MANY_ACTIVE = (f'Ya hay {MAX_ACTIVE_HERO_BANNERS} banners activos, el máximo. '
                   'Desactiva uno antes de activar otro.')


def _upload_dir():
    return current_app.config['BANNER_UPLOAD_DIR']


def _active_count(exclude_id=None):
    query = HeroBanner.query.filter_by(is_active=True)
    if exclude_id is not None:
        query = query.filter(HeroBanner.id != exclude_id)
    return query.count()


def _ordered_banners():
    return HeroBanner.query.order_by(HeroBanner.position, HeroBanner.id).all()


def _parse_date(value):
    """(date or None, error) - a typed value that isn't a date is an error, not "no date"."""
    value = (value or '').strip()
    if not value:
        return None, None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date(), None
    except ValueError:
        return None, 'Una de las fechas no es válida.'


def _form_values(form):
    """What the form sent, as the template shows it back after an error."""
    return {
        'title': clean_name(form.get('title')),
        'text': clean_name(form.get('text')),
        'button_label': clean_name(form.get('button_label')),
        'target_type': form.get('target_type') or 'none',
        'target_product_id': form.get('target_product_id', type=int),
        'target_category_id': form.get('target_category_id', type=int),
        'valid_from': (form.get('valid_from') or '').strip(),
        'valid_until': (form.get('valid_until') or '').strip(),
        'is_active': form.get('is_active') == 'on',
    }


def _banner_values(banner):
    if banner is None:
        return {'title': '', 'text': '', 'button_label': '', 'target_type': 'none', 'target_product_id': None,
                'target_category_id': None, 'valid_from': '', 'valid_until': '', 'is_active': True}
    return {
        'title': banner.title or '', 'text': banner.text or '', 'button_label': banner.button_label or '',
        'target_type': banner.target_type, 'target_product_id': banner.target_product_id,
        'target_category_id': banner.target_category_id,
        'valid_from': banner.valid_from.isoformat() if banner.valid_from else '',
        'valid_until': banner.valid_until.isoformat() if banner.valid_until else '',
        'is_active': banner.is_active,
    }


def validate_banner(values, banner=None):
    """(fields, error): fields ready to set on a HeroBanner, or the first problem found.
    banner is the one being edited (None when creating), for the active-banner limit."""
    if len(values['title']) > TITLE_MAX:
        return None, f'El título puede tener hasta {TITLE_MAX} caracteres.'
    if len(values['text']) > TEXT_MAX:
        return None, f'El texto puede tener hasta {TEXT_MAX} caracteres.'
    if len(values['button_label']) > BUTTON_MAX:
        return None, f'El texto del botón puede tener hasta {BUTTON_MAX} caracteres.'

    target_type = values['target_type']
    if target_type not in HERO_TARGET_TYPES:
        return None, 'Elige a dónde lleva el botón.'
    product_id = category_id = None
    if target_type == 'product':
        product = db.session.get(Product, values['target_product_id']) if values['target_product_id'] else None
        if product is None or not product.is_active:
            return None, 'Elige un producto activo para el botón.'
        product_id = product.id
    elif target_type == 'category':
        category = db.session.get(Category, values['target_category_id']) if values['target_category_id'] else None
        if category is None:
            return None, 'Elige una categoría para el botón.'
        category_id = category.id

    label = values['button_label']
    if label and target_type == 'none':
        return None, 'El botón necesita un destino: un producto o una categoría.'
    if target_type != 'none' and not label:
        return None, 'Escribe el texto del botón (ej. "Ver promo"), o elige "Sin botón".'

    valid_from, error = _parse_date(values['valid_from'])
    if error:
        return None, error
    valid_until, error = _parse_date(values['valid_until'])
    if error:
        return None, error
    if valid_from and valid_until and valid_from > valid_until:
        return None, 'La fecha "desde" no puede ser posterior a la fecha "hasta".'

    becomes_active = values['is_active'] and (banner is None or not banner.is_active)
    if becomes_active and _active_count(exclude_id=banner.id if banner else None) >= MAX_ACTIVE_HERO_BANNERS:
        return None, TOO_MANY_ACTIVE

    return {
        'title': values['title'] or None, 'text': values['text'] or None, 'button_label': label or None,
        'target_type': target_type, 'target_product_id': product_id, 'target_category_id': category_id,
        'valid_from': valid_from, 'valid_until': valid_until, 'is_active': values['is_active'],
    }, None


def _form_context(banner, values):
    return {
        'banner': banner,
        'values': values,
        'products': Product.query.filter_by(is_active=True).order_by(Product.name).all(),
        'categories': Category.query.order_by(Category.name).all(),
        'max_active': MAX_ACTIVE_HERO_BANNERS,
    }


@catalog.route('/banners')
@login_required
@owner_required
def hero_banners():
    banners = _ordered_banners()
    return render_template('panel/hero_banners.html', banners=banners,
                           active_count=sum(1 for b in banners if b.is_active), max_active=MAX_ACTIVE_HERO_BANNERS)


@catalog.route('/banners/new', methods=['GET', 'POST'])
@login_required
@owner_required
def new_hero_banner():
    return _save_banner(None)


@catalog.route('/banners/<int:banner_id>/edit', methods=['GET', 'POST'])
@login_required
@owner_required
def edit_hero_banner(banner_id):
    return _save_banner(HeroBanner.query.get_or_404(banner_id))


def _save_banner(banner):
    if request.method == 'GET':
        return render_template('panel/hero_banner_form.html', **_form_context(banner, _banner_values(banner)))

    values = _form_values(request.form)

    def _redisplay(message):
        flash(message)
        return render_template('panel/hero_banner_form.html', **_form_context(banner, values))

    fields, error = validate_banner(values, banner)
    if error:
        return _redisplay(error)

    desktop_file = request.files.get('desktop_image')
    mobile_file = request.files.get('mobile_image')
    has_desktop = bool(desktop_file and desktop_file.filename)
    has_mobile = bool(mobile_file and mobile_file.filename)
    if banner is None and not has_desktop:
        return _redisplay('Sube la imagen de escritorio: es obligatoria.')

    # New files get new names (no stale browser cache) and the old ones are deleted only
    # after the commit - a failed save never leaves the banner without its image.
    allowed = current_app.config['IMAGE_ALLOWED_EXTENSIONS']
    token = secrets.token_hex(4)
    new_desktop = new_mobile = None
    if has_desktop:
        new_desktop = save_image_with_half(None, desktop_file, _upload_dir(), f'banner_{token}_desktop', allowed,
                                           max_dimension=DESKTOP_MAX_DIMENSION)
        if new_desktop is None:
            return _redisplay('La imagen de escritorio debe ser una imagen (png, jpg, jpeg o webp).')
    if has_mobile:
        new_mobile = save_image(None, mobile_file, _upload_dir(), f'banner_{token}_mobile', allowed,
                                max_dimension=MOBILE_MAX_DIMENSION)
        if new_mobile is None:
            delete_image(_upload_dir(), new_desktop)
            return _redisplay('La imagen móvil debe ser una imagen (png, jpg, jpeg o webp).')

    is_new = banner is None
    if is_new:
        last = HeroBanner.query.order_by(HeroBanner.position.desc()).first()
        banner = HeroBanner(position=(last.position + 1) if last else 0)
        db.session.add(banner)
    replaced = []
    if new_desktop:
        replaced.append(banner.desktop_image)
        banner.desktop_image = new_desktop
    if new_mobile:
        replaced.append(banner.mobile_image)
        banner.mobile_image = new_mobile
    elif request.form.get('remove_mobile_image') == 'on':
        replaced.append(banner.mobile_image)
        banner.mobile_image = None
    for name, value in fields.items():
        setattr(banner, name, value)

    db.session.commit()
    for filename in replaced:
        delete_image(_upload_dir(), filename)
    flash('Banner creado' if is_new else 'Banner guardado')
    return redirect(url_for('catalog.hero_banners'))


@catalog.route('/banners/<int:banner_id>/toggle-active', methods=['POST'])
@login_required
@owner_required
def toggle_hero_banner(banner_id):
    banner = HeroBanner.query.get_or_404(banner_id)
    if not banner.is_active and _active_count() >= MAX_ACTIVE_HERO_BANNERS:
        flash(TOO_MANY_ACTIVE)
        return redirect(url_for('catalog.hero_banners'))
    banner.is_active = not banner.is_active
    db.session.commit()
    flash('Banner activado' if banner.is_active else 'Banner desactivado')
    return redirect(url_for('catalog.hero_banners'))


@catalog.route('/banners/<int:banner_id>/move/<direction>', methods=['POST'])
@login_required
@owner_required
def move_hero_banner(banner_id, direction):
    banners = _ordered_banners()
    index = next((i for i, b in enumerate(banners) if b.id == banner_id), None)
    if index is None or direction not in ('up', 'down'):
        return redirect(url_for('catalog.hero_banners'))
    other = index - 1 if direction == 'up' else index + 1
    if 0 <= other < len(banners):
        banners[index], banners[other] = banners[other], banners[index]
    # Renumber the whole list: positions stay 0..n-1 even after deletions or ties.
    for position, banner in enumerate(banners):
        banner.position = position
    db.session.commit()
    return redirect(url_for('catalog.hero_banners'))


@catalog.route('/banners/<int:banner_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_hero_banner(banner_id):
    banner = HeroBanner.query.get_or_404(banner_id)
    files = [banner.desktop_image, banner.mobile_image]
    db.session.delete(banner)
    db.session.commit()
    for filename in files:
        delete_image(_upload_dir(), filename)
    flash('Banner eliminado')
    return redirect(url_for('catalog.hero_banners'))
