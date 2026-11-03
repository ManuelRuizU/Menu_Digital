// The cart's lines, without the DOM: adding units of a product and reading the lines back
// in the shape bundle_pricing.js prices. Pure functions - the menu loads this file as
// window.CartLines, and tests/js/cart_lines.test.js require()s it, so "the modal adds N
// units" and "the cart charges what the modal said" are checked without a browser.
//
// A cart line: { cartKey, id, name, price, quantity, selectedOptions: [{ id, name, priceDelta }] },
// where price is the unit price with its options included.
;(function (root) {
  'use strict'

  // The cart with `quantity` more units of product with these options. The same product
  // with the same options is the same line (its quantity grows); other options, another line.
  function addUnits (cart, product, selectedOptions, quantity) {
    const sortedOptions = [...selectedOptions].sort((a, b) => a.id - b.id)
    const cartKey = `${product.id}:${sortedOptions.map((o) => o.id).join(',')}`
    const existing = cart.find((item) => item.cartKey === cartKey)
    if (existing) {
      return cart.map((item) => (item === existing ? { ...item, quantity: item.quantity + quantity } : item))
    }
    const unitPrice = product.price + sortedOptions.reduce((sum, o) => sum + o.priceDelta, 0)
    return [...cart, {
      cartKey, id: product.id, name: product.name, price: unitPrice, quantity,
      selectedOptions: sortedOptions.map((o) => ({ id: o.id, name: o.name, priceDelta: o.priceDelta })),
    }]
  }

  // The lines as bundle_pricing.js reads them. optionDelta(productId, optionId) fills in
  // a surcharge a line saved by an older version of the menu didn't carry.
  function pricingLines (cart, optionDelta) {
    return cart.map((item) => ({
      productId: item.id,
      quantity: item.quantity,
      unitPrice: item.price,
      optionDeltas: (item.selectedOptions || []).map((o) =>
        (typeof o.priceDelta === 'number' ? o.priceDelta : (optionDelta ? optionDelta(item.id, o.id) : 0))),
    }))
  }

  function subtotal (cart) {
    return cart.reduce((sum, item) => sum + item.price * item.quantity, 0)
  }

  // { [cartKey]: { amount, promoLabels } } - what each line saves, for the cart's
  // "¡Ahorras $X!": its offer price (offerSavingPerUnit(productId): the struck-through
  // price minus the price, per unit) plus the automatic promos it takes part in.
  // promoDiscounts: [{ label, productIds, amount }] as bundle_pricing.js computed them;
  // a promo mixing several lines is credited once, to the last of them, with its label
  // (it can't be split per line truthfully). Lines that save nothing are left out.
  function lineSavings (cart, offerSavingPerUnit, promoDiscounts) {
    const result = {}
    const credit = (line, amount, label) => {
      if (!(amount > 0)) return
      const entry = result[line.cartKey] || (result[line.cartKey] = { amount: 0, promoLabels: [] })
      entry.amount += amount
      if (label) entry.promoLabels.push(label)
    }
    cart.forEach((line) => credit(line, (offerSavingPerUnit(line.id) || 0) * line.quantity, null))
    ;(promoDiscounts || []).forEach((promo) => {
      const ids = new Set(promo.productIds || [])
      const lines = cart.filter((line) => ids.has(line.id))
      if (lines.length) credit(lines[lines.length - 1], promo.amount, lines.length > 1 ? promo.label : null)
    })
    return result
  }

  function totalSavings (savings) {
    return Object.values(savings).reduce((sum, entry) => sum + entry.amount, 0)
  }

  // The "✓ Agregado" notice after adding a product (mobile): one message, the most useful
  // one, in this order -
  //   a) "Cupón X aplicado" - facts.coupon, only when this add applied it the first time;
  //   a2) "¡Ganaste X de regalo!" - facts.giftWon, only on the add that reached the
  //      amount of the automatic gift;
  //   b) "Agrega 1 más y llévate N por $X" - the next quantity price of a promo the
  //      product is in (facts.nudges: [{ productIds, quantity, totalPrice }],
  //      BundlePricing.nextUnitNudge, the cart's own "Agrega 1 más" line);
  //   c) "Llevas N …: ahorras $X" - a promo with the product discounting the cart now
  //      (facts.promoDiscounts: the cart preview's [{ label, productIds, amount }]); a
  //      one-product promo names the product, a mixed one names the promo;
  //   d) "Te faltan $X para tu regalo" - facts.giftMissing, as the cart's gift hint;
  //   e) just "✓ Agregado".
  function addedNotice (productId, cart, facts, formatPrice) {
    const prefix = '✓ Agregado'
    if (facts.coupon) return `${prefix} · Cupón ${facts.coupon} aplicado`
    if (facts.giftWon) return `${prefix} · ¡Ganaste ${facts.giftWon} de regalo!`
    const nudge = (facts.nudges || []).find((entry) => entry.productIds.includes(productId))
    if (nudge) return `${prefix} · Agrega 1 más y llévate ${nudge.quantity} por ${formatPrice(nudge.totalPrice)}`
    const promo = (facts.promoDiscounts || []).find((entry) => entry.amount > 0 && entry.productIds.includes(productId))
    if (promo) {
      const inPromo = cart.filter((item) => promo.productIds.includes(item.id))
      const units = inPromo.reduce((sum, item) => sum + item.quantity, 0)
      const names = [...new Set(inPromo.map((item) => item.name))]
      const what = promo.productIds.length === 1 && names.length === 1 ? names[0] : `de «${promo.label}»`
      return `${prefix} · Llevas ${units} ${what}: ahorras ${formatPrice(promo.amount)}`
    }
    if (facts.giftMissing > 0) return `${prefix} · Te faltan ${formatPrice(facts.giftMissing)} para tu regalo`
    return prefix
  }

  const api = { addUnits, pricingLines, subtotal, lineSavings, totalSavings, addedNotice }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.CartLines = api
})(this)
