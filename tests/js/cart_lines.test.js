// node --test tests/js   (no dependencies - Node's own test runner)
// The product modal's quantity picker: what it charges for N units, that adding them puts
// ONE line of quantity N in the cart, and that the cart then charges the same - against the
// same vectors the server is checked with (tests/fixtures/modal_cases.json).
const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')

const pricing = require(path.join(__dirname, '../../app/static/js/bundle_pricing.js'))
const cartLines = require(path.join(__dirname, '../../app/static/js/cart_lines.js'))
const { cases } = require(path.join(__dirname, '../fixtures/modal_cases.json'))

const PRODUCT_ID = 8

function promoFor (c) {
  return {
    kind: 'tiered', label: 'Precio por cantidad', productIds: [PRODUCT_ID], featuredQuantity: 3,
    tiers: c.tiers.map(([quantity, totalPrice]) => ({ quantity, totalPrice })),
  }
}

// What the cart shows as its total for these lines (no shipping, no coupon).
function cartTotal (cart, promos) {
  const discount = pricing.bundleDiscounts(promos, cartLines.pricingLines(cart))
    .reduce((sum, entry) => sum + entry.amount, 0)
  return cartLines.subtotal(cart) - discount
}

for (const c of cases) {
  test(`modal == cart: ${c.name}`, () => {
    const product = { id: PRODUCT_ID, name: 'Cheesecake', price: c.unit }
    const options = c.extra_per_unit ? [{ id: 31, name: 'Extra', priceDelta: c.extra_per_unit }] : []

    const modal = pricing.modalTotal(c.unit, c.tiers, c.quantity, c.extra_per_unit)
    const cart = cartLines.addUnits([], product, options, c.quantity)

    assert.equal(modal, c.expected_total)
    assert.equal(cart.length, 1)
    assert.equal(cart[0].quantity, c.quantity)
    assert.equal(cartTotal(cart, [promoFor(c)]), c.expected_total)
  })
}

test('modal without quantity pricing: N x (price + variants)', () => {
  assert.equal(pricing.modalTotal(3200, [], 3, 0), 9600)
  assert.equal(pricing.modalTotal(3200, [], 2, 500), 7400)
})

test('segmented choices: single price first, then every tier with its saving', () => {
  const promo = promoFor({ tiers: [[3, 8990], [2, 6500]] })
  assert.deepEqual(pricing.quantityChoices(3500, promo), [
    { quantity: 1, total: 3500, saving: 0 },
    { quantity: 2, total: 6500, saving: 500 },
    { quantity: 3, total: 8990, saving: 1510 },
  ])
})

test('featured tier: the one featuredQuantity names, else the single price', () => {
  const promo = promoFor({ tiers: [[2, 6500], [3, 8990]] })
  assert.deepEqual(pricing.featuredTier(promo), { quantity: 3, totalPrice: 8990 })
  assert.equal(pricing.featuredTier({ ...promo, featuredQuantity: 1 }), null)
  assert.equal(pricing.featuredTier({ ...promo, featuredQuantity: 5 }), null) // tier gone: single price
  assert.equal(pricing.featuredTier({ ...promo, kind: 'buy_pay' }), null)
  assert.equal(pricing.featuredTier(null), null)
})

test('adding N more of the same product and variants grows that line', () => {
  const product = { id: PRODUCT_ID, name: 'Cheesecake', price: 3500 }
  let cart = cartLines.addUnits([], product, [], 2)
  cart = cartLines.addUnits(cart, product, [], 3)
  assert.equal(cart.length, 1)
  assert.equal(cart[0].quantity, 5)
})

test('other variants are another line, and they still count together for the tiers', () => {
  // Three fillings at $0 added one by one: three lines, priced as 3 units.
  const product = { id: PRODUCT_ID, name: 'Hand roll', price: 3500 }
  let cart = []
  for (const id of [1, 2, 3]) cart = cartLines.addUnits(cart, product, [{ id, name: `R${id}`, priceDelta: 0 }], 1)
  assert.equal(cart.length, 3)
  assert.equal(cartTotal(cart, [promoFor({ tiers: [[2, 6500], [3, 8990]] })]), 8990)
})

test('option order does not make a different line', () => {
  const product = { id: 1, name: 'Pizza', price: 9000 }
  const a = { id: 5, name: 'Queso', priceDelta: 500 }
  const b = { id: 2, name: 'Tocino', priceDelta: 900 }
  let cart = cartLines.addUnits([], product, [a, b], 1)
  cart = cartLines.addUnits(cart, product, [b, a], 2)
  assert.equal(cart.length, 1)
  assert.equal(cart[0].quantity, 3)
  assert.equal(cart[0].price, 10400)
})
