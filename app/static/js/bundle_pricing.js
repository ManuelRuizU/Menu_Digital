// Automatic promo pricing for the cart preview - a line-for-line mirror of
// compute_bundle_discount in app/main/routes.py, which stays the source of truth (the
// server recalculates everything on checkout). Pure functions, no DOM: the menu loads
// this file as window.BundlePricing, and tests/js/bundle_pricing.test.js require()s it
// and runs it against the same vectors as the Python tests
// (tests/fixtures/tiered_cases.json), so the two can't drift apart without a test failing.
//
// A "line" is one cart line: { productId, quantity, unitPrice, optionDeltas }, where
// unitPrice already includes the options and optionDeltas are their price_delta values.
;(function (root) {
  'use strict'

  // tiers: [[quantity, totalPrice], ...]. Cheapest way to pay for n units:
  // best[k] = min(best[k-1] + unit, best[k-q] + tier[q] for q <= k)
  function tieredCostForUnits (unit, tiers, n) {
    const best = new Array(n + 1).fill(0)
    for (let k = 1; k <= n; k++) {
      best[k] = best[k - 1] + unit
      for (const [quantity, totalPrice] of tiers) {
        if (quantity <= k) best[k] = Math.min(best[k], best[k - quantity] + totalPrice)
      }
    }
    return best[n]
  }

  function tieredDiscountForUnits (unit, tiers, n) {
    const discount = n * unit - tieredCostForUnits(unit, tiers, n)
    return discount > 0 ? discount : 0
  }

  // A line's per-unit price without its variants - what a tiered promo prices.
  function lineBasePrice (line) {
    return line.unitPrice - (line.optionDeltas || []).reduce((sum, delta) => sum + delta, 0)
  }

  function matchingLines (promo, lines) {
    const productIds = new Set(promo.productIds)
    return lines.filter((line) => productIds.has(line.productId))
  }

  // "2x1"/"3x2": the cheapest units of each complete group of buyQuantity are free.
  function buyPayDiscount (promo, lines) {
    const unitPrices = []
    matchingLines(promo, lines).forEach((line) => {
      for (let i = 0; i < line.quantity; i++) unitPrices.push(line.unitPrice)
    })
    if (unitPrices.length < promo.buyQuantity) return 0

    unitPrices.sort((a, b) => b - a)
    const freeQuantity = promo.buyQuantity - promo.payQuantity
    let discount = 0
    for (let group = 0; group < Math.floor(unitPrices.length / promo.buyQuantity); group++) {
      const chunk = unitPrices.slice(group * promo.buyQuantity, (group + 1) * promo.buyQuantity)
      if (freeQuantity > 0) discount += chunk.slice(-freeQuantity).reduce((sum, price) => sum + price, 0)
    }
    return discount
  }

  function tiersOf (promo) {
    return (promo.tiers || []).map((tier) => [tier.quantity, tier.totalPrice])
  }

  // { unit, n } for a tiered promo's units in the cart, or null when they don't share
  // one base price (the server skips the promo then - so does this).
  function tieredUnits (promo, lines) {
    const basePrices = []
    matchingLines(promo, lines).forEach((line) => {
      for (let i = 0; i < line.quantity; i++) basePrices.push(lineBasePrice(line))
    })
    if (new Set(basePrices).size > 1) return null
    return { unit: basePrices.length ? basePrices[0] : null, n: basePrices.length }
  }

  function tieredDiscount (promo, lines) {
    const units = tieredUnits(promo, lines)
    if (!units || !units.n || !(promo.tiers || []).length) return 0
    return tieredDiscountForUnits(units.unit, tiersOf(promo), units.n)
  }

  const DISCOUNT_BY_KIND = { buy_pay: buyPayDiscount, tiered: tieredDiscount }

  // An unknown kind is no discount, never an error: a malformed promo must not break the cart.
  function promoDiscount (promo, lines) {
    const compute = DISCOUNT_BY_KIND[promo.kind || 'buy_pay']
    return compute ? Math.round(compute(promo, lines)) : 0
  }

  // [{ promo, amount }] for every promo that actually discounts something right now.
  function bundleDiscounts (promos, lines) {
    return promos
      .map((promo) => ({ promo, amount: promoDiscount(promo, lines) }))
      .filter((entry) => entry.amount > 0)
  }

  // { quantity, totalPrice } when ONE more unit of this tiered promo would save more
  // than now - the same pricing function, not separate rules - else null.
  function nextUnitNudge (promo, lines) {
    if (promo.kind !== 'tiered' || !(promo.tiers || []).length) return null
    const units = tieredUnits(promo, lines)
    if (!units || !units.n) return null
    const tiers = tiersOf(promo)
    const next = units.n + 1
    if (tieredDiscountForUnits(units.unit, tiers, next) <= tieredDiscountForUnits(units.unit, tiers, units.n)) return null
    return { quantity: next, totalPrice: tieredCostForUnits(units.unit, tiers, next) }
  }

  // What the product modal charges for adding `quantity` units of one product on their
  // own: the tiered price of those units (the same function the cart uses, so a single
  // line of `quantity` costs exactly this in the cart too) plus every unit's variant
  // surcharge, which is never discounted. tiers: [[quantity, totalPrice], ...] or [].
  function modalTotal (unit, tiers, quantity, extraPerUnit) {
    return tieredCostForUnits(unit, tiers, quantity) + quantity * (extraPerUnit || 0)
  }

  // The modal's segmented choices for a product with quantity pricing: "1" (the single
  // price) and then one per tier, each with what it costs and saves on the base price.
  function quantityChoices (unit, promo) {
    const tiers = tiersOf(promo)
    const quantities = [1, ...tiers.map(([quantity]) => quantity)]
      .filter((quantity, index, all) => all.indexOf(quantity) === index)
      .sort((a, b) => a - b)
    return quantities.map((quantity) => {
      const total = tieredCostForUnits(unit, tiers, quantity)
      return { quantity, total, saving: quantity * unit - total }
    })
  }

  // The tier the menu card shows big ("3 x $8.990"), or null for the single price - also
  // when featuredQuantity points at a tier that no longer exists.
  function featuredTier (promo) {
    if (!promo || promo.kind !== 'tiered' || !(promo.featuredQuantity > 1)) return null
    return (promo.tiers || []).find((tier) => tier.quantity === promo.featuredQuantity) || null
  }

  const api = {
    tieredCostForUnits,
    tieredDiscountForUnits,
    lineBasePrice,
    promoDiscount,
    bundleDiscounts,
    nextUnitNudge,
    modalTotal,
    quantityChoices,
    featuredTier,
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.BundlePricing = api
})(this)
