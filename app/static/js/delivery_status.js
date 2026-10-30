// The line under Retiro / Despacho in the cart: what the chosen option means for this
// order. Every amount comes in already decided (the shipping cost is the server's, from
// /api/shipping-cost; the total is the cart's preview) - this only words it. The menu
// loads it as window.DeliveryStatus; tests/js require()s it.
;(function (root) {
  'use strict'

  // { text, tone } - tone: 'ok' | 'info' | 'warning'.
  // state: { mode: 'retira'|'envio', pickupAddress, hasLocation, pending, covered, shipping, total }
  function deliveryStatus (state, formatPrice) {
    if (state.mode !== 'envio') {
      return { text: `Retiro en ${state.pickupAddress || 'el local'} · sin costo`, tone: 'ok' }
    }
    if (!state.hasLocation) {
      return { text: 'El despacho tiene costo según tu dirección. Escríbela abajo para calcularlo.', tone: 'info' }
    }
    if (state.pending) return { text: 'Calculando el costo de envío...', tone: 'info' }
    if (!state.covered) return { text: 'No llegamos a esa dirección. Puedes elegir Retiro.', tone: 'warning' }
    const cost = state.shipping > 0 ? `+${formatPrice(state.shipping)}` : 'sin costo'
    return { text: `Envío a tu dirección: ${cost} · Nuevo total: ${formatPrice(state.total)}`, tone: 'ok' }
  }

  const api = { deliveryStatus }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.DeliveryStatus = api
})(this)
