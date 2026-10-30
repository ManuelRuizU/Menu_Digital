// The "¿Con cuánto pagas?" buttons under Efectivo: the exact total, then the total
// rounded up to the next multiple of each bill - amounts a customer can put together
// with real bills, not one single bill. The menu loads it as window.QuickCash;
// tests/js require()s it.
;(function (root) {
  'use strict'

  // Chile's bills (the largest is $20.000); change them here for another country.
  const CASH_DENOMINATIONS = [1000, 5000, 10000, 20000]
  const MAX_BUTTONS = 4

  // [exact, ...rounded up] - ascending, no repeats, only amounts above the total.
  function quickCashAmounts (total, denominations = CASH_DENOMINATIONS) {
    if (!(total > 0)) return []
    const exact = Math.ceil(total)
    const rounded = denominations.map((bill) => Math.ceil(exact / bill) * bill).filter((amount) => amount > exact)
    return [...new Set([exact, ...rounded])].sort((a, b) => a - b).slice(0, MAX_BUTTONS)
  }

  // The "¿Con cuánto pagas?" example: the largest suggestion, never below the total;
  // null (no example) when there's nothing to pay.
  function placeholderAmount (total, denominations = CASH_DENOMINATIONS) {
    const amounts = quickCashAmounts(total, denominations)
    return amounts.length ? amounts[amounts.length - 1] : null
  }

  const api = { CASH_DENOMINATIONS, quickCashAmounts, placeholderAmount }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.QuickCash = api
})(this)
