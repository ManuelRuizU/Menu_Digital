# app/utils.py


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
