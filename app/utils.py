# app/utils.py

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import BUSINESS_TZ


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
