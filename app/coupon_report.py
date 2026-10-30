# app/coupon_report.py
"""`flask coupon-report`: are customers using the coupons? Read-only - it never writes to
the database, so it is safe to run on production. Lists every coupon with its state
today and its uses, then the orders of the last N days with and without a coupon, and
how many of the ones without a coupon could have used a public one (shown in the
banner) - an estimate: it uses the coupon's current settings, not the ones it had on
the order's day."""
from collections import Counter
from datetime import datetime, timedelta, timezone

import click

from app.models import BUSINESS_TZ, Coupon, CouponRedemption, Order


def coupon_state(coupon, today):
    """What a customer typing the code today would find - same order as validate_coupon."""
    if not coupon.is_active:
        return 'inactivo'
    if coupon.valid_from and today < coupon.valid_from:
        return 'aún no vigente'
    if coupon.valid_until and today > coupon.valid_until:
        return 'vencido'
    if coupon.max_total_uses is not None and coupon.total_uses >= coupon.max_total_uses:
        return 'agotado'
    return 'vigente'


def describe_benefit(coupon):
    if coupon.kind == 'product':
        return f'regalo: {coupon.gift_product.name}' if coupon.gift_product else 'regalo (sin producto)'
    if coupon.kind == 'fixed':
        return f'-${coupon.fixed_amount:,}'.replace(',', '.')
    return f'-{coupon.discount_percent:g}%'


def order_products_subtotal(order):
    """Products minus the 2x1-style promos - what the minimum purchase is compared against."""
    lines = sum(item.price * item.quantity for item in order.order_items if not item.is_gift)
    return lines - (order.bundle_discount_amount or 0)


def potential_saving(coupon, order):
    """(applies, saving) for this coupon on an order that didn't use one. Gift coupons
    apply with saving 0 - their benefit is the product, not an amount."""
    day = order.created_at_local.date()
    if coupon.valid_from and day < coupon.valid_from:
        return False, 0
    if coupon.valid_until and day > coupon.valid_until:
        return False, 0
    subtotal = order_products_subtotal(order)
    if coupon.min_order_amount is not None and subtotal < coupon.min_order_amount:
        return False, 0
    if coupon.max_uses_per_customer is not None:
        digits = order.phone_digits
        earlier = sum(1 for r in coupon.redemptions if r.phone_digits == digits and r.created_at < order.created_at)
        if earlier >= coupon.max_uses_per_customer:
            return False, 0
    if coupon.kind == 'product':
        return True, 0
    if coupon.scope == 'products':
        ids = {product.id for product in coupon.products}
        applicable = sum(item.price * item.quantity for item in order.order_items
                         if not item.is_gift and item.product_id in ids)
        if applicable <= 0:
            return False, 0
    else:
        applicable = subtotal + (order.shipping_cost if coupon.applies_to_shipping else 0)
    if coupon.kind == 'fixed':
        return True, min(coupon.fixed_amount, applicable)
    return True, round(applicable * coupon.discount_percent / 100)


def build_report(days=30, now=None):
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    today = now.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TZ).date()

    coupons = Coupon.query.order_by(Coupon.id).all()
    recent_uses = Counter(coupon_id for (coupon_id,) in
                          CouponRedemption.query.with_entities(CouponRedemption.coupon_id)
                          .filter(CouponRedemption.created_at >= since))
    coupon_rows = []
    for coupon in coupons:
        last = max((r.created_at for r in coupon.redemptions), default=None)
        coupon_rows.append({
            'coupon': coupon,
            'state': coupon_state(coupon, today),
            'benefit': describe_benefit(coupon),
            'uses': coupon.total_uses,
            'recent_uses': recent_uses.get(coupon.id, 0),
            'last_use': last,
        })

    orders = Order.query.filter(Order.created_at >= since).order_by(Order.created_at).all()
    valid = [o for o in orders if o.status != 'Cancelled']
    with_coupon = [o for o in valid if o.coupon_id]
    without = [o for o in valid if not o.coupon_id]

    public = [c for c in coupons if c.is_active and c.show_in_banner]
    missed, missed_saving, missed_by_code = 0, 0, Counter()
    for order in without:
        best = None
        for coupon in public:
            applies, saving = potential_saving(coupon, order)
            if applies and (best is None or saving > best[1]):
                best = (coupon, saving)
        if best:
            missed += 1
            missed_saving += best[1]
            missed_by_code[best[0].code] += 1

    return {
        'days': days,
        'today': today,
        'coupons': coupon_rows,
        'orders_total': len(orders),
        'orders_cancelled': len(orders) - len(valid),
        'orders_valid': len(valid),
        'orders_with_coupon': len(with_coupon),
        'orders_with_coupon_by_code': Counter(o.coupon.code for o in with_coupon if o.coupon),
        'discount_total': sum(o.discount_amount or 0 for o in with_coupon),
        'confirmed_valid': sum(1 for o in valid if o.status == 'Confirmed'),
        'confirmed_with_coupon': sum(1 for o in with_coupon if o.status == 'Confirmed'),
        'missed': missed,
        'missed_saving': missed_saving,
        'missed_by_code': missed_by_code,
    }


def _money(amount):
    return f'${amount:,}'.replace(',', '.')


def _percent(part, whole):
    return f'{(100 * part / whole):.0f}%' if whole else '-'


@click.command('coupon-report')
@click.option('--days', default=30, show_default=True, help='Ventana de pedidos a revisar, en días.')
def coupon_report_command(days):
    """Uso de cupones (solo lectura): estado de cada cupón, usos, y pedidos de los últimos
    N días con y sin cupón, más los que pudieron usar un cupón público y no lo hicieron."""
    report = build_report(days)
    click.echo(f'Cupones (hoy {report["today"].isoformat()}):')
    if not report['coupons']:
        click.echo('  (no hay cupones)')
    for row in report['coupons']:
        c = row['coupon']
        validity = (f'{c.valid_from.isoformat() if c.valid_from else "…"} a '
                    f'{c.valid_until.isoformat() if c.valid_until else "…"}')
        limits = []
        if c.min_order_amount:
            limits.append(f'mínimo {_money(c.min_order_amount)}')
        if c.max_total_uses is not None:
            limits.append(f'máx {c.max_total_uses} usos')
        if c.max_uses_per_customer is not None:
            limits.append(f'{c.max_uses_per_customer} por cliente')
        if c.scope == 'products':
            limits.append(f'solo {len(c.products)} producto(s)')
        last = row['last_use'].strftime('%Y-%m-%d') if row['last_use'] else 'nunca'
        click.echo(f'  - {c.code}: {row["benefit"]} · {row["state"]} · '
                   f'{"público (banner)" if c.show_in_banner else "privado"} · vigencia {validity}'
                   f'{" · " + ", ".join(limits) if limits else ""}')
        click.echo(f'      usos: {row["uses"]} en total, {row["recent_uses"]} en {report["days"]} días · '
                   f'último: {last}')

    valid = report['orders_valid']
    click.echo(f'\nPedidos de los últimos {report["days"]} días: {report["orders_total"]} '
               f'({report["orders_cancelled"]} cancelados, no se cuentan abajo)')
    click.echo(f'  con cupón: {report["orders_with_coupon"]} de {valid} '
               f'({_percent(report["orders_with_coupon"], valid)}) · '
               f'descuento total {_money(report["discount_total"])}')
    for code, count in report['orders_with_coupon_by_code'].most_common():
        click.echo(f'      {code}: {count}')
    click.echo(f'  confirmados: {report["confirmed_valid"]}, de ellos con cupón: {report["confirmed_with_coupon"]}')
    click.echo(f'  sin cupón pero cumplían un cupón público: {report["missed"]} de '
               f'{valid - report["orders_with_coupon"]} · ahorro que no tomaron {_money(report["missed_saving"])}')
    for code, count in report['missed_by_code'].most_common():
        click.echo(f'      {code}: {count}')
    click.echo('  (estimación con la configuración actual de cada cupón)')
