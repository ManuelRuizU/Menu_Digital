# app/utils.py

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import BUSINESS_TZ

REQUESTED_TIME_RE = re.compile(r'^\d{2}:\d{2}$')


def day_range_utc(local_date):
    """Dado un date local de Santiago, devuelve (start_utc, end_utc): el rango
    [inicio, fin) del día en UTC naive, para filtrar Order.created_at.
    end_utc es exclusivo (< end_utc), igual que hoy."""
    start_local = datetime.combine(local_date, time.min, tzinfo=BUSINESS_TZ)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
    end_utc = end_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
    return start_utc, end_utc


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


def validate_order_fields(data, delivery_mode):
    """Valida los campos obligatorios de un pedido nuevo, antes de tocar la base.
    Devuelve (ok, error_message) - error_message es None si ok es True.
    Reglas: customer_name, phone y requested_time son obligatorios siempre (y
    requested_time debe venir en formato HH:MM - un valor presente pero mal
    formado no debe colarse silenciosamente como si fuera válido). address es
    obligatoria solo si delivery_mode == 'envio' (despacho); en retiro es opcional
    (el negocio ya sabe su propia dirección de retiro)."""
    if not (data.get('customerName') or '').strip():
        return False, 'Falta indicar el nombre.'
    if not (data.get('phone') or '').strip():
        return False, 'Falta indicar el teléfono.'
    requested_time = (data.get('requestedTime') or '').strip()
    if not requested_time or not REQUESTED_TIME_RE.match(requested_time):
        return False, 'Falta indicar el horario sugerido.'
    if delivery_mode == 'envio' and not (data.get('address') or '').strip():
        return False, 'Falta indicar la dirección de despacho.'
    return True, None
