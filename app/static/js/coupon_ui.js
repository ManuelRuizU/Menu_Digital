// The cart's coupon texts and decisions, apart from the DOM: the coupon card, the
// applied/waiting box, the reminder before sending and the coupon kept for this tab.
// Every amount here comes from the server (/api/cart-coupons, /api/apply-coupon) - this
// only words it. The menu loads it as window.CouponUI; tests/js require()s it.
;(function (root) {
  'use strict'

  const STORAGE_KEY = 'menu-digital-coupon'
  const SOURCES = ['card', 'banner', 'reminder', 'manual']
  // A rejection worded as a thank-you, not as an error.
  const FRIENDLY_REASONS = ['already_used']
  // Up to this many cards show; past it, the first ones and "Ver todos los cupones (N)".
  const OFFERS_SHOWN = 3

  // { title, detail, saving, canApply } for one /api/cart-coupons entry.
  function offerLines (offer, formatPrice) {
    if (offer.status === 'min_order') {
      return { title: offer.code, detail: `Agrega ${formatPrice(offer.missing)} más para usar ${offer.code}`, saving: '', canApply: false }
    }
    return {
      title: offer.code,
      detail: offer.description,
      saving: offer.kind === 'product' ? '' : `Ahorras ${formatPrice(offer.saving)}`,
      canApply: true,
    }
  }

  // How the cart's coupon section is laid out. offers: the server's list (it puts the
  // ones that apply first, by saving), minus the one already applied. With no public
  // coupon, no title and nothing to show - and the manual box asks for "un código".
  function offersLayout (offers) {
    const count = offers.length
    const folded = count > OFFERS_SHOWN
    return {
      title: count ? `🎁 Cupones disponibles para ti (${count})` : '',
      shown: folded ? offers.slice(0, OFFERS_SHOWN) : offers,
      more: folded ? offers.slice(OFFERS_SHOWN) : [],
      moreLabel: folded ? `Ver todos los cupones (${count})` : '',
      manualTitle: count ? '¿Tienes otro código?' : '¿Tienes un código de descuento?',
    }
  }

  // "✓ DULCE aplicado: −$1.200" / "✓ REGALO aplicado: Té helado gratis".
  function appliedText (coupon, formatPrice) {
    const benefit = coupon.kind === 'product'
      ? `${coupon.giftProductName} gratis`
      : `−${formatPrice(coupon.discountAmount)}`
    return `✓ ${coupon.code} aplicado: ${benefit}`
  }

  function reminderText (offer, formatPrice) {
    return offer.kind === 'product'
      ? `¿Quieres aplicar ${offer.code} y llevarte gratis ${offer.giftProductName}?`
      : `¿Quieres aplicar ${offer.code} y ahorrar ${formatPrice(offer.saving)}?`
  }

  // The coupon to remind about: the server's first one that applies (it already sorts
  // by saving). Not when a coupon is applied, nor twice for the same order.
  function reminderOffer (offers, { applied, alreadyShown }) {
    if (applied || alreadyShown) return null
    return (offers || []).find((offer) => offer.status === 'ok') || null
  }

  // 'ok' | 'info' | 'thanks' | 'error' - how the box shows a coupon response.
  function messageTone (response) {
    if (response.ok) return 'ok'
    if (FRIENDLY_REASONS.includes(response.reason)) return 'thanks'
    if (response.waits) return 'info'
    return 'error'
  }

  // The coupon kept for this tab (sessionStorage): survives a reload, gone when the
  // tab closes or the order is sent. Any storage error just means "nothing kept".
  function loadKept (storage) {
    try {
      const kept = JSON.parse(storage.getItem(STORAGE_KEY) || 'null')
      if (kept && typeof kept.code === 'string' && kept.code.trim()) {
        return { code: kept.code.trim().toUpperCase().slice(0, 30), source: SOURCES.includes(kept.source) ? kept.source : 'manual' }
      }
    } catch {}
    return null
  }

  function saveKept (storage, coupon) {
    try {
      if (coupon) storage.setItem(STORAGE_KEY, JSON.stringify({ code: coupon.code, source: coupon.source }))
      else storage.removeItem(STORAGE_KEY)
    } catch {}
  }

  const api = { STORAGE_KEY, offerLines, offersLayout, appliedText, reminderText, reminderOffer, messageTone, loadKept, saveKept }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.CouponUI = api
})(this)
