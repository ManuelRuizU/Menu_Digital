# app/catalog/coupon_usage.py
"""Panel "Uso de cupones": what customers do with the coupons in the menu (the
CouponAttempt log) next to the orders with and without a coupon (the same numbers as
`flask coupon-report`)."""
from flask import render_template, request
from flask_login import login_required

from app.catalog import catalog
from app.coupon_attempts import RETENTION_DAYS, purge_old, usage_summary
from app.coupon_report import build_report
from app.decorators import owner_required

DAY_CHOICES = (7, 30, 90)
SOURCE_LABELS = {'card': 'Tarjeta del carrito', 'banner': 'Banner', 'reminder': 'Recordatorio',
                 'manual': 'Escrito a mano', 'unknown': 'Sin origen (página antigua)'}
REASON_LABELS = {'not_found': 'no existe', 'not_yet': 'aún no vigente', 'expired': 'vencido',
                 'exhausted': 'agotado', 'phone_required': 'faltaba el teléfono', 'already_used': 'ya usado',
                 'min_order': 'compra mínima', 'not_in_cart': 'no aplica a esos productos',
                 'gift_unavailable': 'regalo sin stock', 'unknown': 'otro'}


@catalog.route('/coupons/usage')
@login_required
@owner_required
def coupon_usage():
    days = request.args.get('days', 30, type=int)
    if days not in DAY_CHOICES:
        days = 30
    purge_old()
    return render_template('panel/coupon_usage.html', usage=usage_summary(days), report=build_report(days),
                           days=days, day_choices=DAY_CHOICES, source_labels=SOURCE_LABELS,
                           reason_labels=REASON_LABELS, retention_days=RETENTION_DAYS)
