const test = require('node:test')
const assert = require('node:assert/strict')
const { deliveryStatus } = require('../../app/static/js/delivery_status.js')

const formatPrice = (value) => '$' + Math.round(value).toLocaleString('es-CL')
const base = { mode: 'envio', pickupAddress: 'Sevilla 632, Angol', hasLocation: true, pending: false, covered: true, shipping: 1500, total: 9690 }

test('retiro: the pickup address, free', () => {
  assert.deepEqual(deliveryStatus({ ...base, mode: 'retira' }, formatPrice), { text: 'Retiro en Sevilla 632, Angol · sin costo', tone: 'ok' })
  assert.equal(deliveryStatus({ ...base, mode: 'retira', pickupAddress: '' }, formatPrice).text, 'Retiro en el local · sin costo')
})

test('despacho: no address, calculating, in zone, free, out of zone', () => {
  assert.equal(deliveryStatus({ ...base, hasLocation: false }, formatPrice).text,
    'El despacho tiene costo según tu dirección. Escríbela abajo para calcularlo.')
  assert.equal(deliveryStatus({ ...base, pending: true }, formatPrice).text, 'Calculando el costo de envío...')
  assert.deepEqual(deliveryStatus(base, formatPrice), { text: 'Envío a tu dirección: +$1.500 · Nuevo total: $9.690', tone: 'ok' })
  assert.equal(deliveryStatus({ ...base, shipping: 0 }, formatPrice).text, 'Envío a tu dirección: sin costo · Nuevo total: $9.690')
  assert.deepEqual(deliveryStatus({ ...base, covered: false }, formatPrice), { text: 'No llegamos a esa dirección. Puedes elegir Retiro.', tone: 'warning' })
})
