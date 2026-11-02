# app/seasons.py
"""Seasonal decorations for the public menu ("Adornos de temporada"): the catalog of
celebrations the owner can switch on (all off by default), their own celebrations, and
which one the menu shows on a given Santiago day. Everything is decided here, on the
server - the browser only plays the effects it is handed (app/static/js/seasonal.js)."""
import re
import unicodedata
from datetime import date, timedelta

from app.models import Celebration

# Fixed dates: ((start month, day), (end month, day)), both inclusive - an end before the
# start crosses New Year. Computed ones: an anchor day per year (a Sunday) and how many
# days before it the celebration starts.
FIXED, COMPUTED = 'fixed', 'computed'
CUSTOM_KIND, PRESET_KIND = 'custom', 'preset'
PERSONAL_MOTIF = 'personal'
MAX_EMOJIS = 3
NAME_MAX = 40
HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


def easter_sunday(year):
    """Western (Gregorian) Easter Sunday - the anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_sunday(year, month, n):
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


# The catalog, in the order the panel lists it (and the tie-break for overlaps).
# band: the header's thin stripe (a CSS gradient, or the accent alone).
MOTIFS = {
    'navidad': dict(name='Navidad', accent='#c62828', band='linear-gradient(90deg, #c62828, #2e7d32, #c62828)',
                    particle='❄️', burst=['🎄', '🎁', '⭐'], crossing='🦌🦌🛷🎅',
                    dates=(FIXED, ((12, 1), (12, 25)))),
    'ano_nuevo': dict(name='Año Nuevo', accent='#d4af37', band='linear-gradient(90deg, #d4af37, #fff3b0, #d4af37)',
                      particle='✨', burst=['🥂', '🎉', '🎆'], crossing='🎆',
                      dates=(FIXED, ((12, 26), (1, 1)))),
    'san_valentin': dict(name='San Valentín', accent='#e91e63', band=None,
                         particle='💗', burst=['💘', '❤️', '🌹'], crossing='💘',
                         dates=(FIXED, ((2, 7), (2, 14)))),
    'san_patricio': dict(name='San Patricio', accent='#2e7d32', band=None,
                         particle='☘️', burst=['🍀', '🌈', '🪙'], crossing='🌈',
                         dates=(FIXED, ((3, 14), (3, 17)))),
    'pascua': dict(name='Pascua', accent='#ab47bc', band='linear-gradient(90deg, #ab47bc, #ffd54f, #81c784)',
                   particle='🥚', burst=['🐣', '🐰', '🥚'], crossing='🐇',
                   dates=(COMPUTED, (easter_sunday, 6))),
    'dia_madre': dict(name='Día de la Madre', accent='#ec407a', band=None,
                      particle='🌸', burst=['💐', '🌷', '💖'], crossing='💐',
                      dates=(COMPUTED, (lambda year: nth_sunday(year, 5, 2), 6))),
    'dia_padre': dict(name='Día del Padre', accent='#1e88e5', band=None,
                      particle='⭐', burst=['👔', '🏆', '💙'], crossing='🏆',
                      dates=(COMPUTED, (lambda year: nth_sunday(year, 6, 3), 6))),
    'orgullo': dict(name='Orgullo', accent='#e040fb',
                    band='linear-gradient(90deg, #e53935, #fb8c00, #fdd835, #43a047, #1e88e5, #8e24aa)',
                    particle='🌈', burst=['🏳️‍🌈', '✨', '💖'], crossing='🏳️‍🌈',
                    dates=(FIXED, ((6, 22), (6, 28)))),
    'dia_nino': dict(name='Día del Niño', accent='#ffb300', band=None,
                     particle='🎈', burst=['🧸', '🎈', '🍭'], crossing='🎈',
                     dates=(COMPUTED, (lambda year: nth_sunday(year, 8, 2), 6))),
    'fiestas_patrias': dict(name='Fiestas Patrias', accent='#d52b1e',
                            band='linear-gradient(90deg, #0039a6, #ffffff, #d52b1e)',
                            particle='⭐', burst=['🇨🇱', '🥟', '🪁'], crossing='🪁',
                            dates=(FIXED, ((9, 10), (9, 19)))),
    'halloween': dict(name='Halloween', accent='#ff7518', band=None,
                      particle='🍂', burst=['🎃', '👻', '🍬'], crossing='🧙‍♀️🧹',
                      dates=(FIXED, ((10, 25), (10, 31)))),
}
MOTIF_ORDER = list(MOTIFS)


# --- Dates -------------------------------------------------------------------------------

def _md_date(year, month, day):
    """A month/day in a given year - 29/02 falls on the 28th in a non-leap year."""
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, day - 1)


def parse_md(value):
    """'MM-DD' -> (month, day), or None if it isn't a real day (29/02 is)."""
    match = re.fullmatch(r'(\d{2})-(\d{2})', value or '')
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    try:
        date(2024, month, day)  # a leap year, so 29/02 counts
    except ValueError:
        return None
    return month, day


def parse_day_month(value):
    """'25/12' or '5/1' as the owner types it -> 'MM-DD' as stored, or None."""
    match = re.fullmatch(r'(\d{1,2})/(\d{1,2})', (value or '').strip())
    if not match:
        return None
    stored = f'{int(match.group(2)):02d}-{int(match.group(1)):02d}'
    return stored if parse_md(stored) else None


def day_month(stored):
    """'MM-DD' -> '25/12', for the panel."""
    month, day = parse_md(stored)
    return f'{day:02d}/{month:02d}'


def preset_rule(celebration):
    """The date rule of a catalog celebration, with the owner's edits over the defaults."""
    kind, rule = MOTIFS[celebration.motif]['dates']
    if kind == FIXED:
        start = parse_md(celebration.start_md) or rule[0]
        end = parse_md(celebration.end_md) or rule[1]
        return FIXED, (start, end)
    anchor, days_before = rule
    if celebration.days_before is not None:
        days_before = celebration.days_before
    return COMPUTED, (anchor, days_before)


def occurrence(celebration, year):
    """(start, end) of the celebration's occurrence that starts in `year`, or None (a
    one-off celebration of the owner's in another year)."""
    if celebration.kind == CUSTOM_KIND:
        if celebration.start_date and celebration.start_date.year == year:
            return celebration.start_date, celebration.end_date
        return None
    kind, rule = preset_rule(celebration)
    if kind == FIXED:
        (start_month, start_day), (end_month, end_day) = rule
        start = _md_date(year, start_month, start_day)
        crosses_year = (end_month, end_day) < (start_month, start_day)
        end = _md_date(year + 1 if crosses_year else year, end_month, end_day)
        return start, end
    anchor, days_before = rule
    end = anchor(year)
    return end - timedelta(days=days_before), end


def occurrences(celebration, first_year, last_year):
    found = (occurrence(celebration, year) for year in range(first_year, last_year + 1))
    return [span for span in found if span]


def current_span(celebration, today):
    """The (start, end) covering today, or None. Looks at last year's too: Año Nuevo,
    26/12 to 1/1, started last year when today is 1 January."""
    for start, end in occurrences(celebration, today.year - 1, today.year):
        if start <= today <= end:
            return start, end
    return None


def _priority(celebration, span):
    """Shortest range first; a tie goes to the owner's own, then catalog order."""
    start, end = span
    catalog_index = MOTIF_ORDER.index(celebration.motif) if celebration.kind == PRESET_KIND else -1
    return ((end - start).days, 0 if celebration.kind == CUSTOM_KIND else 1, catalog_index, celebration.id or 0)


def _switched_on():
    return Celebration.query.filter_by(is_active=True).all()


def active_celebration(today, celebrations=None):
    """(celebration, span) the menu shows today, or None."""
    celebrations = _switched_on() if celebrations is None else celebrations
    live = [(c, span) for c in celebrations for span in [current_span(c, today)] if span]
    if not live:
        return None
    return min(live, key=lambda pair: _priority(*pair))


def next_celebration(today, celebrations=None, days=365):
    """(celebration, start) of the next one to begin after today, within a year."""
    celebrations = _switched_on() if celebrations is None else celebrations
    upcoming = [(start, c) for c in celebrations
                for start, _ in occurrences(c, today.year, today.year + 1)
                if today < start <= today + timedelta(days=days)]
    if not upcoming:
        return None
    start, celebration = min(upcoming, key=lambda pair: pair[0])
    return celebration, start


def overlap_warnings(today, celebrations=None, days=365):
    """Messages for switched-on celebrations whose dates collide in the coming year,
    naming the one the menu will show."""
    celebrations = _switched_on() if celebrations is None else celebrations
    window_end = today + timedelta(days=days)
    spans = [(c, span) for c in celebrations
             for span in occurrences(c, today.year - 1, today.year + 1)
             if span[1] >= today and span[0] <= window_end]
    warnings = []
    for i, (first, first_span) in enumerate(spans):
        for second, second_span in spans[i + 1:]:
            if first is second:
                continue
            start, end = max(first_span[0], second_span[0]), min(first_span[1], second_span[1])
            if start > end:
                continue
            winner = min(((first, first_span), (second, second_span)), key=lambda pair: _priority(*pair))[0]
            same_day = start == end
            when = f'el {start:%d/%m}' if same_day else f'del {start:%d/%m} al {end:%d/%m}'
            warnings.append(f'{display_name(first)} y {display_name(second)} se solapan {when}; '
                            f'se mostrará {display_name(winner)}.')
    return warnings


# --- How it looks ------------------------------------------------------------------------

def display_name(celebration):
    if celebration.kind == CUSTOM_KIND:
        return f'«{celebration.name}»'
    return MOTIFS[celebration.motif]['name']


def look(celebration, preview=False):
    """What the menu's page gets: colors, emojis, which effects. Only values from the
    catalog or already validated (emojis, #hex) - the template still escapes them."""
    if celebration.kind == CUSTOM_KIND and celebration.motif == PERSONAL_MOTIF:
        emojis = split_emojis(celebration.emojis)
        accent = celebration.accent
        motif = dict(name=celebration.name, accent=accent, band=None,
                     particle=emojis[0] if emojis else '✨', burst=emojis or ['✨'],
                     crossing=''.join(emojis))
    else:
        motif = MOTIFS[celebration.motif]
    name = celebration.name if celebration.kind == CUSTOM_KIND else motif['name']
    particles = split_emojis(celebration.emojis) if celebration.motif == PERSONAL_MOTIF else [motif['particle']]
    return {
        'name': name,
        'accent': motif['accent'],
        'band': motif['band'] or motif['accent'],
        'particles': particles or [motif['particle']],
        'burst': motif['burst'],
        'crossing': motif['crossing'],
        'ambient': bool(celebration.ambient),
        'burstOn': bool(celebration.burst),
        'preview': preview,
    }


def preset(key):
    """The catalog celebration's row, created (switched off) the first time it's needed."""
    from app import db
    row = Celebration.query.filter_by(kind=PRESET_KIND, motif=key).first()
    if row is None:
        row = Celebration(kind=PRESET_KIND, motif=key, is_active=False, ambient=True, burst=True)
        db.session.add(row)
    return row


def find_for_preview(value):
    """'navidad' (catalog) or 'c12' (the owner's celebration 12) -> a Celebration, or None.
    A catalog one never touched yet is previewed with its defaults, without saving a row."""
    value = (value or '').strip()
    if value in MOTIFS:
        return (Celebration.query.filter_by(kind=PRESET_KIND, motif=value).first()
                or Celebration(kind=PRESET_KIND, motif=value, ambient=True, burst=True))
    match = re.fullmatch(r'c(\d{1,9})', value)
    if match:
        return Celebration.query.filter_by(kind=CUSTOM_KIND, id=int(match.group(1))).first()
    return None


def preview_key(celebration):
    return celebration.motif if celebration.kind == PRESET_KIND else f'c{celebration.id}'


def menu_season(today, owner, preview_value=None, can_preview=False):
    """The `season` dict for the menu page: the owner's preview when asked for (and
    allowed), else today's celebration - None when the master switch is off or there is
    nothing to show."""
    if preview_value and can_preview:
        celebration = find_for_preview(preview_value)
        if celebration is not None:
            return look(celebration, preview=True)
    if not owner or not owner.seasonal_decor_enabled:
        return None
    found = active_celebration(today)
    return look(found[0]) if found else None


# --- Validation (the owner's own celebrations) -------------------------------------------

# Code points an emoji can be built from: pictographs and symbols, regional-indicator
# flags, skin tones, ZWJ sequences, variation selector 16, tag sequences (subdivision
# flags) and keycaps. Letters, digits on their own, punctuation, spaces and '<' are not.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2300, 0x23FF), (0x2B00, 0x2BFF), (0x2190, 0x21FF),
    (0x25A0, 0x25FF), (0x2900, 0x297F), (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297),
    (0x3299, 0x3299), (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049),
    (0x2122, 0x2122), (0x2139, 0x2139),
)
_JOINERS = {0x200D, 0xFE0F, 0x20E3}
_TAGS = (0xE0020, 0xE007F)


def _is_pictograph(code):
    return any(low <= code <= high for low, high in _EMOJI_RANGES)


def is_single_emoji(value):
    """True when value is exactly one emoji (a flag, a ZWJ family and a skin tone count as
    one) - never text, HTML or several emojis."""
    if not value or len(value) > 16 or value != value.strip():
        return False
    codes = [ord(char) for char in value]
    regional = [c for c in codes if 0x1F1E6 <= c <= 0x1F1FF]
    if regional:
        return len(regional) == 2 and len(codes) == 2
    if codes[0] in (0x23, 0x2A) or 0x30 <= codes[0] <= 0x39:  # keycap: 1️⃣ #️⃣
        return codes[1:] in ([0xFE0F, 0x20E3], [0x20E3])
    pictographs = 0
    expect_pictograph = True
    for code in codes:
        if code in _JOINERS:
            if code == 0x200D:
                expect_pictograph = True
            continue
        if _TAGS[0] <= code <= _TAGS[1] or 0x1F3FB <= code <= 0x1F3FF:
            continue
        if not _is_pictograph(code) or unicodedata.category(chr(code)) in ('Lu', 'Ll', 'Nd', 'Zs'):
            return False
        if not expect_pictograph:
            return False  # two pictographs side by side: two emojis
        pictographs += 1
        expect_pictograph = False
    return pictographs >= 1


def split_emojis(value):
    return [part for part in (value or '').split(' ') if part]


def validate_custom(form, today):
    """(fields, error) for the owner's own celebration form."""
    name = ' '.join((form.get('name') or '').split())
    if not name:
        return None, 'Escribe el nombre de la celebración.'
    if len(name) > NAME_MAX:
        return None, f'El nombre puede tener hasta {NAME_MAX} caracteres.'
    try:
        start = date.fromisoformat((form.get('start_date') or '').strip())
        end = date.fromisoformat((form.get('end_date') or '').strip())
    except ValueError:
        return None, 'Elige las fechas «desde» y «hasta».'
    if start > end:
        return None, 'La fecha «desde» no puede ser posterior a la fecha «hasta».'
    if (end - start).days > 92:
        return None, 'Una celebración puede durar hasta 3 meses.'
    motif = form.get('motif') or ''
    if motif not in MOTIFS and motif != PERSONAL_MOTIF:
        return None, 'Elige un motivo.'
    emojis, accent = None, None
    if motif == PERSONAL_MOTIF:
        typed = [(form.get(f'emoji_{n}') or '').strip() for n in range(1, MAX_EMOJIS + 1)]
        typed = [value for value in typed if value]
        if not typed:
            return None, 'Escribe al menos un emoji.'
        if not all(is_single_emoji(value) for value in typed):
            return None, 'Cada casilla debe tener un solo emoji (sin letras ni otros signos).'
        accent = (form.get('accent') or '').strip()
        if not HEX_COLOR.match(accent):
            return None, 'Elige un color de acento válido (ej. #c62828).'
        emojis = ' '.join(typed)
        accent = accent.lower()
    return {
        'name': name, 'start_date': start, 'end_date': end, 'motif': motif, 'emojis': emojis,
        'accent': accent, 'ambient': form.get('ambient') == 'on', 'burst': form.get('burst') == 'on',
        'is_active': form.get('is_active') == 'on',
    }, None


def validate_preset(key, form):
    """(fields, error) for a catalog celebration's row: on/off, dates, effects."""
    kind, _ = MOTIFS[key]['dates']
    fields = {'is_active': form.get('is_active') == 'on', 'ambient': form.get('ambient') == 'on',
              'burst': form.get('burst') == 'on'}
    if kind == FIXED:
        start, end = parse_day_month(form.get('start_md')), parse_day_month(form.get('end_md'))
        if not start or not end:
            return None, 'Escribe las fechas como día/mes, por ejemplo 1/12 y 25/12.'
        fields.update(start_md=start, end_md=end)
    else:
        try:
            days_before = int(form.get('days_before', ''))
        except ValueError:
            return None, 'Escribe cuántos días antes empieza (0 a 30).'
        if not 0 <= days_before <= 30:
            return None, 'Escribe cuántos días antes empieza (0 a 30).'
        fields['days_before'] = days_before
    return fields, None
