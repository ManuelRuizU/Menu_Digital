// node --test tests/js
const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')

const { buildWhatsAppLines, submitOrder, formatPrice } = require(path.join(__dirname, '../../app/static/js/order_message.js'))

const customer = {
  name: 'Ana', phone: '56911112222', deliveryMode: 'envio', address: 'Calle 1', paymentLabel: 'Efectivo',
  paymentMethod: 'efectivo', cashAmount: 10000, requestedTimeLabel: '19:00', notes: '',
}

const order = {
  lines: [{ name: 'Hand roll pollo', quantity: 3, options: ['Extra palta'], total: 9470 }],
  subtotal: 9470,
  shipping: 1500,
  promos: [{ label: 'Hand rolls', amount: 1980 }, { label: '2x1 bebidas', amount: 1500 }],
  coupon: { code: 'DIEZ', kind: 'percent', amount: 549 },
  gift: { name: 'Mochi', couponCode: null, threshold: 8000 },
  total: 6941,
}

test('every amount in the message comes from the server response', () => {
  const text = buildWhatsAppLines(order, customer).join('\n')
  assert.match(text, /• 3× Hand roll pollo \(Extra palta\) - \$9\.470/)
  assert.match(text, /• 1× Mochi - de regalo 🎁 \(por compra sobre \$8\.000\)/)
  assert.match(text, /Subtotal: \$9\.470/)
  assert.match(text, /Envío: \$1\.500/)
  assert.match(text, /Hand rolls: -\$1\.980/)
  assert.match(text, /2x1 bebidas: -\$1\.500/)
  assert.match(text, /Descuento \(DIEZ\): -\$549/)
  assert.match(text, /Total: \$6\.941/)
  assert.match(text, /Paga con: \$10\.000 \(vuelto \$3\.059\)/) // change computed from the server total
})

test('a gift coupon shows its gift line, not a $0 discount line', () => {
  const giftCouponOrder = { ...order, promos: [], coupon: { code: 'REGALO', kind: 'product', amount: 0 },
    gift: { name: 'Mochi', couponCode: 'REGALO', threshold: null } }
  const text = buildWhatsAppLines(giftCouponOrder, customer).join('\n')
  assert.match(text, /• 1× Mochi - de regalo 🎁 \(cupón REGALO\)/)
  assert.doesNotMatch(text, /Descuento \(REGALO\)/)
})

test('pickup has no shipping line', () => {
  const text = buildWhatsAppLines(order, { ...customer, deliveryMode: 'retira' }).join('\n')
  assert.doesNotMatch(text, /Envío:/)
  assert.doesNotMatch(text, /Dirección:/)
})

test('formatPrice uses Chilean thousands separators like the rest of the menu', () => {
  assert.equal(formatPrice(16970), '$16.970')
})

test('a failed save shows the error and never opens WhatsApp', async () => {
  const calls = []
  const sent = await submitOrder({
    save: async () => ({ ok: false, message: 'Sin stock' }),
    open: () => calls.push('open'),
    onFailure: (message) => calls.push(`failure:${message}`),
    onSent: () => calls.push('sent'),
  })
  assert.equal(sent, false)
  assert.deepEqual(calls, ['failure:Sin stock'])
})

test('a successful save opens WhatsApp once, with the saved order, then clears', async () => {
  const calls = []
  await submitOrder({
    save: async () => ({ ok: true, order: { total: 6990 } }),
    open: (saved) => calls.push(`open:${saved.total}`),
    onFailure: () => calls.push('failure'),
    onSent: () => calls.push('sent'),
  })
  assert.deepEqual(calls, ['open:6990', 'sent'])
})
