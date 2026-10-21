# app/utils.py

import re
import unicodedata
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import BUSINESS_TZ

REQUESTED_TIME_RE = re.compile(r'^\d{2}:\d{2}$')


def clean_name(value):
    """A catalog name as it's SAVED: what the owner typed, with the surrounding spaces
    trimmed and runs of inner spaces collapsed to one. Case and accents are kept."""
    return ' '.join((value or '').split())


def normalize_name(value):
    """A catalog name as it's COMPARED, never saved: clean_name, casefolded, without
    accents (NFKD, combining marks dropped) - so "Sushi"/"SUSHI", "Hand  Roll"/"Hand Roll"
    and "Maracuyá"/"Maracuya" are the same name. Ñ is a letter, not an accented N: "Piña"
    and "Pina" stay different. Done in Python, not SQL: SQLite's lower() only folds ASCII
    and it has no accent stripping at all."""
    decomposed = unicodedata.normalize('NFKD', clean_name(value).casefold())
    kept = []
    for char in decomposed:
        # NFKD splits ñ into n + U+0303 (combining tilde): that one mark stays, on an n.
        if unicodedata.combining(char) and not (char == '̃' and kept and kept[-1] == 'n'):
            continue
        kept.append(char)
    return unicodedata.normalize('NFC', ''.join(kept))


def day_range_utc(local_date):
    """Dado un date local de Santiago, devuelve (start_utc, end_utc): el rango
    [inicio, fin) del día en UTC naive, para filtrar Order.created_at.
    end_utc es exclusivo (< end_utc), igual que hoy."""
    start_local = datetime.combine(local_date, time.min, tzinfo=BUSINESS_TZ)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
    end_utc = end_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
    return start_utc, end_utc


HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def hex_to_rgb(value):
    """'#rrggbb' -> 'r, g, b' (para usar en rgba(var(--x-rgb), alpha) en CSS).
    None o un hex mal formado -> None, para que el caller decida el fallback."""
    if not value or not HEX_COLOR_RE.match(value):
        return None
    r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
    return f'{r}, {g}, {b}'


def parse_money(data, field, default=None):
    """Lee un monto CLP desde un form o un dict JSON.
    Acepta '7200', '7200.0', 7200 y 7200.0. Devuelve int o default."""
    raw = data.get(field)
    if raw is None:
        return default
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return default
    try:
        return round(float(raw))
    except (TypeError, ValueError):
        return default


CUSTOMER_NAME_MAX_LENGTH = 60


def customer_name_parts(data):
    """(first_name, last_name) from a create_order payload, as they're SAVED (clean_name).
    last_name is None when the payload has no customerLastName key at all - a menu page
    loaded before the last name existed, whose order must still go through - and ''
    when the key is there but blank (the current form, which requires it)."""
    def text(key):
        value = data.get(key)
        return clean_name(value) if isinstance(value, str) else ''
    last_name = text('customerLastName') if 'customerLastName' in data else None
    return text('customerName'), last_name


def phone_customer_key(phone):
    """Who a phone number belongs to, for grouping orders by customer: its digits, and
    for Chile only the last 9 (the mobile number without the 56 country code), so
    "+56 9 1234 5678", "56912345678" and "912345678" are the same customer."""
    digits = re.sub(r'\D', '', phone or '')
    return digits[-9:]


def validate_order_fields(data, delivery_mode):
    """Valida los campos obligatorios de un pedido nuevo, antes de tocar la base.
    Devuelve (ok, error_message) - error_message es None si ok es True.
    Reglas: customer_name, phone y requested_time son obligatorios siempre (y
    requested_time debe venir en formato HH:MM - un valor presente pero mal
    formado no debe colarse silenciosamente como si fuera válido). El apellido es
    obligatorio solo si el payload trae la clave customerLastName (la carta actual
    siempre la manda; una carta abierta antes del deploy no, y ese pedido se acepta).
    address es obligatoria solo si delivery_mode == 'envio' (despacho); en retiro es
    opcional (el negocio ya sabe su propia dirección de retiro)."""
    first_name, last_name = customer_name_parts(data)
    if not first_name:
        return False, 'Falta indicar el nombre.'
    if len(first_name) > CUSTOMER_NAME_MAX_LENGTH:
        return False, 'El nombre es muy largo.'
    if last_name is not None:
        if not last_name:
            return False, 'Falta indicar el apellido.'
        if len(last_name) > CUSTOMER_NAME_MAX_LENGTH:
            return False, 'El apellido es muy largo.'
    if not (data.get('phone') or '').strip():
        return False, 'Falta indicar el teléfono.'
    requested_time = (data.get('requestedTime') or '').strip()
    if not requested_time or not REQUESTED_TIME_RE.match(requested_time):
        return False, 'Falta indicar el horario sugerido.'
    if delivery_mode == 'envio' and not (data.get('address') or '').strip():
        return False, 'Falta indicar la dirección de despacho.'
    return True, None
