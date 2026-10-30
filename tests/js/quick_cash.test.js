const test = require('node:test')
const assert = require('node:assert/strict')
const { CASH_DENOMINATIONS, quickCashAmounts } = require('../../app/static/js/quick_cash.js')

test('Chile bills: no $50.000 bill', () => {
  assert.deepEqual(CASH_DENOMINATIONS, [1000, 5000, 10000, 20000])
})

test('exact, then the total rounded up to each bill', () => {
  assert.deepEqual(quickCashAmounts(27480), [27480, 28000, 30000, 40000])
  assert.deepEqual(quickCashAmounts(12300), [12300, 13000, 15000, 20000])
  assert.deepEqual(quickCashAmounts(4200), [4200, 5000, 10000, 20000])
})

test('a round total: only amounts above it, no repeats', () => {
  assert.deepEqual(quickCashAmounts(30000), [30000, 40000])
  assert.deepEqual(quickCashAmounts(20000), [20000])
})

test('totals over $50.000 still get useful amounts, at most 4', () => {
  assert.deepEqual(quickCashAmounts(63500), [63500, 64000, 65000, 70000])
})

test('nothing to pay, nothing to suggest; cents round up', () => {
  assert.deepEqual(quickCashAmounts(0), [])
  assert.deepEqual(quickCashAmounts(-10), [])
  assert.deepEqual(quickCashAmounts(4199.5), [4200, 5000, 10000, 20000])
})

test('the bills can change per country', () => {
  assert.deepEqual(quickCashAmounts(870, [100, 500, 1000]), [870, 900, 1000])
})

test('placeholder: the largest suggestion, never below the total; none with nothing to pay', () => {
  const { placeholderAmount } = require('../../app/static/js/quick_cash.js')
  assert.equal(placeholderAmount(27480), 40000)
  assert.equal(placeholderAmount(20000), 20000)
  assert.equal(placeholderAmount(63500), 70000)
  assert.equal(placeholderAmount(0), null)
  for (const total of [1, 999, 4200, 30000, 99999]) assert.ok(placeholderAmount(total) >= total)
})
