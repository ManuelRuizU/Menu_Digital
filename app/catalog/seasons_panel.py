# app/catalog/seasons_panel.py
"""Panel "Adornos de temporada": the master switch, the catalog's celebrations (each off
until the owner switches it on, dates editable) and the owner's own. The rules - which
one shows, overlaps, what a valid emoji is - live in app/seasons.py."""
from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.catalog import catalog
from app.decorators import owner_required
from app.models import BUSINESS_TZ, Celebration
from app.seasons import (COMPUTED, CUSTOM_KIND, MOTIF_ORDER, MOTIFS, PERSONAL_MOTIF, PRESET_KIND, active_celebration,
                         current_span, display_name, next_celebration, occurrences, overlap_warnings,
                         preset, preset_rule, preview_key, split_emojis, validate_custom, validate_preset)


def _today():
    return datetime.now(BUSINESS_TZ).date()


def _upcoming_span(celebration, today):
    """The occurrence happening now, else the next one - what the panel shows as dates."""
    span = current_span(celebration, today)
    if span:
        return span
    ahead = [s for s in occurrences(celebration, today.year, today.year + 1) if s[0] > today]
    return min(ahead) if ahead else None


def _preset_rows(today):
    saved = {c.motif: c for c in Celebration.query.filter_by(kind=PRESET_KIND).all()}
    rows = []
    for key in MOTIF_ORDER:
        celebration = saved.get(key) or Celebration(kind=PRESET_KIND, motif=key, is_active=False,
                                                    ambient=True, burst=True)
        kind, rule = preset_rule(celebration)
        row = {'key': key, 'motif': MOTIFS[key], 'celebration': celebration, 'computed': kind == COMPUTED,
               'span': _upcoming_span(celebration, today), 'preview': preview_key(celebration)}
        if kind == COMPUTED:
            row['days_before'] = rule[1]
        else:
            row['start'] = f'{rule[0][1]:02d}/{rule[0][0]:02d}'
            row['end'] = f'{rule[1][1]:02d}/{rule[1][0]:02d}'
        rows.append(row)
    return rows


@catalog.route('/temporada')
@login_required
@owner_required
def seasons():
    today = _today()
    switched_on = Celebration.query.filter_by(is_active=True).all()
    showing = active_celebration(today, switched_on)
    upcoming = next_celebration(today, switched_on)
    customs = Celebration.query.filter_by(kind=CUSTOM_KIND).order_by(Celebration.start_date).all()
    return render_template(
        'panel/seasons.html',
        enabled=current_user.seasonal_decor_enabled,
        showing=(display_name(showing[0]), showing[1]) if showing else None,
        upcoming=(display_name(upcoming[0]), upcoming[1]) if upcoming else None,
        warnings=overlap_warnings(today, switched_on),
        presets=_preset_rows(today),
        customs=[{'celebration': c, 'preview': preview_key(c),
                  'look': MOTIFS[c.motif]['name'] if c.motif in MOTIFS else ' '.join(split_emojis(c.emojis))}
                 for c in customs],
    )


@catalog.route('/temporada/interruptor', methods=['POST'])
@login_required
@owner_required
def seasons_switch():
    current_user.seasonal_decor_enabled = request.form.get('enabled') == 'on'
    db.session.commit()
    flash('Adornos de temporada encendidos' if current_user.seasonal_decor_enabled else 'Adornos de temporada apagados')
    return redirect(url_for('catalog.seasons'))


@catalog.route('/temporada/catalogo/<key>', methods=['POST'])
@login_required
@owner_required
def save_preset_celebration(key):
    if key not in MOTIFS:
        abort(404)
    fields, error = validate_preset(key, request.form)
    if error:
        flash(error)
        return redirect(url_for('catalog.seasons') + f'#c-{key}')
    row = preset(key)
    for name, value in fields.items():
        setattr(row, name, value)
    db.session.commit()
    flash(f'{MOTIFS[key]["name"]}: guardado')
    return redirect(url_for('catalog.seasons') + f'#c-{key}')


def _custom_values(celebration):
    if celebration is None:
        return {'name': '', 'start_date': '', 'end_date': '', 'motif': PERSONAL_MOTIF, 'emojis': ['', '', ''],
                'accent': '#c62828', 'ambient': True, 'burst': True, 'is_active': True}
    emojis = split_emojis(celebration.emojis) + ['', '', '']
    return {'name': celebration.name, 'start_date': celebration.start_date.isoformat(),
            'end_date': celebration.end_date.isoformat(), 'motif': celebration.motif, 'emojis': emojis[:3],
            'accent': celebration.accent or '#c62828', 'ambient': celebration.ambient, 'burst': celebration.burst,
            'is_active': celebration.is_active}


def _form_values(form):
    return {'name': form.get('name', ''), 'start_date': form.get('start_date', ''), 'end_date': form.get('end_date', ''),
            'motif': form.get('motif', PERSONAL_MOTIF),
            'emojis': [form.get(f'emoji_{n}', '') for n in (1, 2, 3)],
            'accent': form.get('accent', '#c62828'), 'ambient': form.get('ambient') == 'on',
            'burst': form.get('burst') == 'on', 'is_active': form.get('is_active') == 'on'}


def _save_custom(celebration):
    if request.method == 'GET':
        return render_template('panel/celebration_form.html', celebration=celebration,
                               values=_custom_values(celebration), motifs=MOTIFS, motif_order=MOTIF_ORDER)
    fields, error = validate_custom(request.form, _today())
    if error:
        flash(error)
        return render_template('panel/celebration_form.html', celebration=celebration,
                               values=_form_values(request.form), motifs=MOTIFS, motif_order=MOTIF_ORDER)
    if celebration is None:
        celebration = Celebration(kind=CUSTOM_KIND)
        db.session.add(celebration)
    for name, value in fields.items():
        setattr(celebration, name, value)
    db.session.commit()
    flash(f'«{celebration.name}» guardada')
    return redirect(url_for('catalog.seasons'))


@catalog.route('/temporada/nueva', methods=['GET', 'POST'])
@login_required
@owner_required
def new_celebration():
    return _save_custom(None)


@catalog.route('/temporada/<int:celebration_id>/editar', methods=['GET', 'POST'])
@login_required
@owner_required
def edit_celebration(celebration_id):
    return _save_custom(Celebration.query.filter_by(id=celebration_id, kind=CUSTOM_KIND).first_or_404())


@catalog.route('/temporada/<int:celebration_id>/borrar', methods=['POST'])
@login_required
@owner_required
def delete_celebration(celebration_id):
    celebration = Celebration.query.filter_by(id=celebration_id, kind=CUSTOM_KIND).first_or_404()
    db.session.delete(celebration)
    db.session.commit()
    flash(f'«{celebration.name}» borrada')
    return redirect(url_for('catalog.seasons'))
