// node --test tests/js   (no dependencies - Node's own test runner)
// Runs the menu's promo pricing against the same vectors as the Python tests.
const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')

const pricing = require(path.join(__dirname, '../../app/static/js/bundle_pricing.js'))
const { cases } = require(path.join(__dirname, '../fixtures/tiered_cases.json'))

for (const c of cases) {
  test(`tiered vector: ${c.name}`, () => {
    assert.equal(pricing.tieredCostForUnits(c.unit, c.tiers, c.n), c.expected_cost)
    assert.equal(pricing.tieredDiscountForUnits(c.unit, c.tiers, c.n), c.expected_discount)
  })
}

const tiered = { kind: 'tiered', productIds: [1, 2], tiers: [{ quantity: 2, totalPrice: 4990 }, { quantity: 3, totalPrice: 6990 }] }
const line = (productId, quantity, unitPrice = 2990, optionDeltas = []) => ({ productId, quantity, unitPrice, optionDeltas })

test('tiered promo mixes products and ignores products outside it', () => {
  assert.equal(pricing.promoDiscount(tiered, [line(1, 2), line(2, 1), line(99, 5)]), 3 * 2990 - 6990)
})

test('a variant surcharge is charged in full, never discounted', () => {
  // second unit carries +500: the tier prices both 2990 bases, the 500 stays on top
  assert.equal(pricing.promoDiscount(tiered, [line(1, 1), line(1, 1, 3490, [500])]), 2 * 2990 - 4990)
})

test('tiered promo whose units no longer share one base price gives no discount', () => {
  assert.equal(pricing.promoDiscount(tiered, [line(1, 1, 2990), line(2, 1, 3490)]), 0)
})

test('unknown kind gives no discount instead of throwing', () => {
  assert.equal(pricing.promoDiscount({ kind: 'bogus', productIds: [1] }, [line(1, 3)]), 0)
})

test('buy_pay: cheapest units of each complete group are free (same as Python)', () => {
  const twoForOne = { kind: 'buy_pay', productIds: [1, 2], buyQuantity: 2, payQuantity: 1 }
  assert.equal(pricing.promoDiscount(twoForOne, [line(1, 1, 4200), line(2, 1, 3800)]), 3800)
  assert.equal(pricing.promoDiscount(twoForOne, [line(1, 3, 4200)]), 4200) // third unit: incomplete group
})

test('bundleDiscounts lists each promo that applies, with its amount', () => {
  const twoForOne = { kind: 'buy_pay', productIds: [7], buyQuantity: 2, payQuantity: 1, label: '2x1' }
  const result = pricing.bundleDiscounts([tiered, twoForOne], [line(1, 3), line(7, 1, 1500)])
  assert.deepEqual(result.map((entry) => entry.amount), [1980]) // the 2x1 has only 1 unit -> left out
})

test('nudge only when one more unit saves more, naming that exact total', () => {
  assert.deepEqual(pricing.nextUnitNudge(tiered, [line(1, 1)]), { quantity: 2, totalPrice: 4990 })
  assert.deepEqual(pricing.nextUnitNudge(tiered, [line(1, 2)]), { quantity: 3, totalPrice: 6990 })
  assert.equal(pricing.nextUnitNudge(tiered, [line(1, 3)]), null) // 4 saves the same as 3
  assert.deepEqual(pricing.nextUnitNudge(tiered, [line(1, 4)]), { quantity: 5, totalPrice: 11980 })
  assert.equal(pricing.nextUnitNudge(tiered, []), null) // nothing of the promo in the cart yet
  assert.equal(pricing.nextUnitNudge(tiered, [line(1, 1, 2990), line(2, 1, 3490)]), null) // mismatched prices
})
