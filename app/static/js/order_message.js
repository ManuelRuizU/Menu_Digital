// The customer's WhatsApp message and the save-then-open sequence, as pure functions:
// the menu loads this file as window.OrderMessage, and tests/js require()s it.
//
// Every amount in the message comes from create_order's response (what the server just
// saved) - never from the cart's preview - so the message always matches total_price.
;(function (root) {
  'use strict'

  function formatPrice (value) {
    return `$${Number(value).toLocaleString('es-CL')}`
  }

  function giftReason (gift) {
    return gift.couponCode ? `cupón ${gift.couponCode}` : `por compra sobre ${formatPrice(gift.threshold)}`
  }

  // "Nombre Apellido" with single spaces (like the server's clean_name), and no stray
  // space when either is blank.
  function fullName (name, lastName) {
    return [name, lastName].join(' ').split(/\s+/).filter(Boolean).join(' ')
  }

  // order: the create_order response. customer: what the customer typed, already read
  // from the form - { name, lastName, phone, deliveryMode, address, paymentLabel,
  // paymentMethod, cashAmount, requestedTimeLabel, notes }.
  function buildWhatsAppLines (order, customer) {
    const lines = [
      'Hola! Quiero hacer un pedido desde el menú digital:',
      `Nombre: ${fullName(customer.name, customer.lastName)}`,
      `Teléfono: ${customer.phone}`,
      `Tipo: ${customer.deliveryMode === 'envio' ? 'Despacho' : 'Retiro'}`,
    ]
    if (customer.deliveryMode === 'envio') lines.push(`Dirección: ${customer.address}`)
    lines.push(`Pago: ${customer.paymentLabel}`)
    if (customer.paymentMethod === 'efectivo' && customer.cashAmount > 0) {
      const cash = customer.cashAmount
      lines.push(cash >= order.total
        ? `Paga con: ${formatPrice(cash)} (vuelto ${formatPrice(cash - order.total)})`
        : `Paga con: ${formatPrice(cash)}`)
    }
    lines.push(`Hora sugerida: ${customer.requestedTimeLabel || 'No indicada'}`)
    if (customer.notes) lines.push(`Notas: ${customer.notes}`)

    lines.push('', 'Productos:')
    order.lines.forEach((line) => {
      const optionsText = line.options && line.options.length ? ` (${line.options.join(', ')})` : ''
      lines.push(`• ${line.quantity}× ${line.name}${optionsText} - ${formatPrice(line.total)}`)
    })
    if (order.gift) lines.push(`• 1× ${order.gift.name} - de regalo 🎁 (${giftReason(order.gift)})`)

    lines.push('', `Subtotal: ${formatPrice(order.subtotal)}`)
    if (customer.deliveryMode === 'envio') lines.push(`Envío: ${formatPrice(order.shipping)}`)
    order.promos.forEach((promo) => lines.push(`${promo.label}: -${formatPrice(promo.amount)}`))
    // A gift coupon has no amount - its gift is already listed under "Productos:".
    if (order.coupon && order.coupon.kind !== 'product') {
      lines.push(`Descuento (${order.coupon.code}): -${formatPrice(order.coupon.amount)}`)
    }
    lines.push(`Total: ${formatPrice(order.total)}`)
    lines.push('', 'Gracias!')
    return lines
  }

  // save() -> { ok, order } | { ok: false, message }. WhatsApp opens only once the order
  // is saved, with the server's amounts; a failed save shows the error, opens nothing,
  // and leaves the cart alone for a retry. open() runs right after the single await, so
  // the browser still sees it as part of the customer's tap.
  async function submitOrder ({ save, open, onFailure, onSent }) {
    const result = await save()
    if (!result.ok) {
      onFailure(result.message)
      return false
    }
    open(result.order)
    onSent()
    return true
  }

  const api = { formatPrice, fullName, buildWhatsAppLines, submitOrder }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.OrderMessage = api
})(this)
