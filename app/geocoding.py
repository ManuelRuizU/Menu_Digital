# app/geocoding.py
"""Server-side geocoding (address -> coordinates), first implementation in Python.

DEUDA A ANOTAR: el geocoding hoy vive en 3 lugares independientes - menu.js
(searchAddress/reverseGeocode, checkout público), un <script> inline en
panel/index.html (dirección del propio negocio), y esta función (nueva, para la
Agenda). Ninguno comparte código con los otros. Habría que centralizar en una sola
interfaz - sobre todo pensando en el soporte opcional de Google Maps por negocio a
futuro, donde un solo punto de entrada podría elegir el proveedor. No se resuelve
ahora, queda anotado para cuando se aborde ese soporte.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from flask import current_app

NOMINATIM_TIMEOUT_SECONDS = 5


def _user_agent():
    # Nominatim's usage policy requires an identifiable User-Agent - this can't be
    # set from a browser fetch() (browsers block overriding it), which is exactly
    # why the two existing frontend geocoding call sites can't comply with this part
    # of the policy either. Server-side, we can and must.
    creator = current_app.config.get('CREATOR_NAME') or 'MenuDigital'
    return f'{creator}-MenuDigital-Agenda/1.0'


def geocode(address):
    """Geocodes a free-text address via Nominatim. Returns (lat, lon) as floats,
    or None if the address wasn't found, the request failed, or timed out - never
    raises. Callers should treat None as "couldn't geocode", not as an error to
    surface as a 500."""
    address = (address or '').strip()
    if not address:
        return None

    query = urllib.parse.urlencode({'format': 'json', 'q': address, 'limit': 1})
    url = f'https://nominatim.openstreetmap.org/search?{query}'
    request = urllib.request.Request(url, headers={'User-Agent': _user_agent()})

    try:
        with urllib.request.urlopen(request, timeout=NOMINATIM_TIMEOUT_SECONDS) as response:
            results = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None

    if not results:
        return None

    try:
        return float(results[0]['lat']), float(results[0]['lon'])
    except (KeyError, TypeError, ValueError):
        return None
