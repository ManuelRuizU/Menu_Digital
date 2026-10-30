# app/storefront.py
"""What the top of the public menu shows above the carta - the big carousel (owner
banners, then banner coupons) and "Explora el menú" - built
on the server, so the first slide is in the HTML the browser gets (no layout jump, and
fetchpriority actually applies) and every rule is checked here, never in the browser."""
import os

from flask import current_app, url_for

from app.models import MAX_ACTIVE_HERO_BANNERS, HeroBanner, Product
from app.uploads import half_width_filename

def clp(amount):
    """7990 -> '$7.990', same as formatPrice in the menu's JS."""
    return '$' + f'{int(amount):,}'.replace(',', '.')


def upload_url(subdir, filename):
    return url_for('static', filename=f'uploads/{subdir}/{filename}') if filename else None


def upload_half_url(subdir, filename):
    """The 960w copy's URL, only if it exists - images saved before it existed have none."""
    if not filename:
        return None
    half = half_width_filename(filename)
    if not os.path.exists(os.path.join(current_app.static_folder, 'uploads', subdir, half)):
        return None
    return upload_url(subdir, half)


def _banner_button(banner):
    """(label, kind, id) for a banner's button, or None when it has nowhere valid to go:
    a product that's inactive or sold out, or a category with nothing on the menu."""
    if not banner.button_label:
        return None
    if banner.target_type == 'product':
        product = banner.target_product
        if product is None or not product.is_active or product.sold_out:
            return None
        return banner.button_label, 'product', product.id
    if banner.target_type == 'category':
        category = banner.target_category
        if category is None or not Product.query.filter_by(category_id=category.id, is_active=True).first():
            return None
        return banner.button_label, 'category', category.id
    return None


def banner_slide(banner):
    return {
        'kind': 'banner',
        'image': upload_url('banners', banner.desktop_image),
        'image_half': upload_half_url('banners', banner.desktop_image),
        'mobile_image': upload_url('banners', banner.mobile_image),
        'title': banner.title,
        'text': banner.text,
        'button': _banner_button(banner),
    }


def coupon_slide(coupon):
    """Same wording the menu's JS used for a banner coupon. With the owner's artwork, one
    headline over it; without, the discount itself, large, on the theme's colors."""
    is_gift = coupon.kind == 'product'
    gift_name = coupon.gift_product.name if is_gift and coupon.gift_product else ''
    discount = clp(coupon.fixed_amount or 0) if coupon.kind == 'fixed' else f'{coupon.discount_percent or 0:g}%'
    min_order = f'Con compra sobre {clp(coupon.min_order_amount)}' if coupon.min_order_amount else ''
    validity = f"Válido hasta {coupon.valid_until.strftime('%d-%m-%Y')}" if coupon.valid_until else ''
    scope = 'En toda tu compra' if coupon.scope == 'order' else 'En productos seleccionados'
    image = upload_url('coupons', coupon.banner_image_filename)
    slide = {'kind': 'coupon', 'code': coupon.code, 'image': image,
             'image_half': upload_half_url('coupons', coupon.banner_image_filename), 'mobile_image': None}
    if image:
        slide.update(label='🏷️ Cupón',
                     title=f'🎁 {gift_name} gratis con {coupon.code}' if is_gift else f'{discount} OFF con {coupon.code}',
                     detail=' · '.join(part for part in (min_order, validity) if part))
    else:
        slide.update(label='🏷️ Usa el código',
                     big='🎁' if is_gift else f'-{discount}',
                     title=coupon.code,
                     detail=' · '.join(part for part in (f'{gift_name} de regalo' if is_gift else scope,
                                                         min_order, validity) if part))
    return slide


def coupon_benefit_text(coupon):
    """What the coupon gives, in a line: the cart's coupon card and its reminder."""
    if coupon.kind == 'product':
        return f'Llévate gratis {coupon.gift_product.name}' if coupon.gift_product else 'Un regalo con tu pedido'
    amount = clp(coupon.fixed_amount or 0) if coupon.kind == 'fixed' else f'{coupon.discount_percent or 0:g}%'
    if coupon.scope == 'products':
        names = [product.name for product in coupon.products]
        where = ', '.join(names[:2]) + (f' y {len(names) - 2} más' if len(names) > 2 else '')
        return f'{amount} de descuento en {where}'
    return f'{amount} de descuento en tu pedido' + (' (incluye el envío)' if coupon.applies_to_shipping else '')


def hero_slides(today, banner_coupons):
    """Owner banners first (active, in their dates, by position), then the coupons the
    caller already filtered for the banner (active, dated, uses left, gift in stock)."""
    banners = (HeroBanner.query.filter_by(is_active=True)
               .order_by(HeroBanner.position, HeroBanner.id).all())
    current = [banner for banner in banners if banner.is_current(today)][:MAX_ACTIVE_HERO_BANNERS]
    return [banner_slide(banner) for banner in current] + [coupon_slide(coupon) for coupon in banner_coupons]


def explore_categories(products):
    """[{'id', 'name', 'image'}] for each category with an active product, in menu order.
    image: the category's own photo, else its first product photo, else None (the
    template then draws a colored tile)."""
    tiles, seen = [], {}
    for product in products:
        if not product.is_active:
            continue
        category = product.category
        if category.id not in seen:
            seen[category.id] = {'id': category.id, 'name': category.name,
                                 'image': upload_url('categories', category.image_filename)}
            tiles.append(seen[category.id])
        tile = seen[category.id]
        if tile['image'] is None and product.image_filename:
            tile['image'] = upload_url('products', product.image_filename)
    return tiles

