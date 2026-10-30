const test = require('node:test')
const assert = require('node:assert/strict')
const CouponUI = require('../../app/static/js/coupon_ui.js')

const formatPrice = (value) => '$' + Math.round(value).toLocaleString('es-CL')

test('offerLines: applicable coupon shows its saving and a button', () => {
  const lines = CouponUI.offerLines({ code: 'DULCE', kind: 'percent', status: 'ok', saving: 1200, description: '10% de descuento en tu pedido' }, formatPrice)
  assert.deepEqual(lines, { title: 'DULCE', detail: '10% de descuento en tu pedido', saving: 'Ahorras $1.200', canApply: true })
})

test('offerLines: short of the minimum says how much more, no button', () => {
  const lines = CouponUI.offerLines({ code: 'DULCE', kind: 'percent', status: 'min_order', missing: 2500, saving: 0 }, formatPrice)
  assert.equal(lines.detail, 'Agrega $2.500 más para usar DULCE')
  assert.equal(lines.canApply, false)
})

test('offerLines: a gift coupon has no "Ahorras" line', () => {
  const lines = CouponUI.offerLines({ code: 'REGALO', kind: 'product', status: 'ok', saving: 2500, description: 'Llévate gratis Té helado' }, formatPrice)
  assert.equal(lines.detail, 'Llévate gratis Té helado')
  assert.equal(lines.saving, '')
})

test('appliedText and reminderText', () => {
  assert.equal(CouponUI.appliedText({ code: 'DULCE', kind: 'percent', discountAmount: 320 }, formatPrice), '✓ DULCE aplicado: −$320')
  assert.equal(CouponUI.appliedText({ code: 'REGALO', kind: 'product', giftProductName: 'Té helado' }, formatPrice), '✓ REGALO aplicado: Té helado gratis')
  assert.equal(CouponUI.reminderText({ code: 'DULCE', kind: 'fixed', saving: 2000 }, formatPrice), '¿Quieres aplicar DULCE y ahorrar $2.000?')
  assert.equal(CouponUI.reminderText({ code: 'REGALO', kind: 'product', giftProductName: 'Té helado' }, formatPrice), '¿Quieres aplicar REGALO y llevarte gratis Té helado?')
})

test('reminderOffer: first applicable, never with a coupon applied or twice', () => {
  const offers = [{ code: 'CORTO', status: 'min_order' }, { code: 'DULCE', status: 'ok' }, { code: 'OTRO', status: 'ok' }]
  assert.equal(CouponUI.reminderOffer(offers, { applied: false, alreadyShown: false }).code, 'DULCE')
  assert.equal(CouponUI.reminderOffer(offers, { applied: true, alreadyShown: false }), null)
  assert.equal(CouponUI.reminderOffer(offers, { applied: false, alreadyShown: true }), null)
  assert.equal(CouponUI.reminderOffer([{ code: 'CORTO', status: 'min_order' }], { applied: false, alreadyShown: false }), null)
  assert.equal(CouponUI.reminderOffer(undefined, { applied: false, alreadyShown: false }), null)
})

test('messageTone: already used is a thank-you, cart reasons wait', () => {
  assert.equal(CouponUI.messageTone({ ok: true }), 'ok')
  assert.equal(CouponUI.messageTone({ ok: false, reason: 'already_used' }), 'thanks')
  assert.equal(CouponUI.messageTone({ ok: false, reason: 'min_order', waits: true }), 'info')
  assert.equal(CouponUI.messageTone({ ok: false, reason: 'expired' }), 'error')
})

function memoryStorage () {
  const data = {}
  return { getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v) }, removeItem: (k) => { delete data[k] }, data }
}

test('kept coupon: saved, loaded, cleared; junk and broken storage are "nothing"', () => {
  const storage = memoryStorage()
  CouponUI.saveKept(storage, { code: 'DULCE', source: 'banner' })
  assert.deepEqual(CouponUI.loadKept(storage), { code: 'DULCE', source: 'banner' })
  CouponUI.saveKept(storage, null)
  assert.equal(CouponUI.loadKept(storage), null)
  storage.setItem(CouponUI.STORAGE_KEY, '{not json')
  assert.equal(CouponUI.loadKept(storage), null)
  storage.setItem(CouponUI.STORAGE_KEY, JSON.stringify({ code: ' dulce ', source: 'evil' }))
  assert.deepEqual(CouponUI.loadKept(storage), { code: 'DULCE', source: 'manual' })
  const broken = { getItem () { throw new Error('blocked') }, setItem () { throw new Error('blocked') }, removeItem () {} }
  assert.equal(CouponUI.loadKept(broken), null)
  assert.doesNotThrow(() => CouponUI.saveKept(broken, { code: 'X', source: 'card' }))
})

test('offersLayout: no public coupon, no section; the box asks for "un código"', () => {
  assert.deepEqual(CouponUI.offersLayout([]), {
    title: '', shown: [], more: [], moreLabel: '', manualTitle: '¿Tienes un código de descuento?',
  })
})

test('offersLayout: up to 3 coupons all show, no "Ver todos"', () => {
  const offers = [{ code: 'A' }, { code: 'B' }, { code: 'C' }]
  const one = CouponUI.offersLayout(offers.slice(0, 1))
  assert.equal(one.title, '🎁 Cupones disponibles para ti (1)')
  assert.equal(one.manualTitle, '¿Tienes otro código?')
  const three = CouponUI.offersLayout(offers)
  assert.deepEqual(three.shown.map((o) => o.code), ['A', 'B', 'C'])
  assert.deepEqual(three.more, [])
  assert.equal(three.moreLabel, '')
})

test('offersLayout: 4 or more show the first 3 (the server sorts them) and "Ver todos"', () => {
  const layout = CouponUI.offersLayout([{ code: 'A' }, { code: 'B' }, { code: 'C' }, { code: 'D' }, { code: 'E' }])
  assert.equal(layout.title, '🎁 Cupones disponibles para ti (5)')
  assert.deepEqual(layout.shown.map((o) => o.code), ['A', 'B', 'C'])
  assert.deepEqual(layout.more.map((o) => o.code), ['D', 'E'])
  assert.equal(layout.moreLabel, 'Ver todos los cupones (5)')
})
