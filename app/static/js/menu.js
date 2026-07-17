const CART_KEY = 'menu-digital-cart'
const CUSTOMER_KEY = 'menu-digital-customer'

function loadSavedCart() {
  try {
    const saved = JSON.parse(localStorage.getItem(CART_KEY) || '[]')
    // Carts saved before variants existed have no cartKey/selectedOptions - backfill them.
    return saved.map((item) => ({
      selectedOptions: [],
      ...item,
      cartKey: item.cartKey || String(item.id),
    }))
  } catch {
    return []
  }
}

const STATE = { products: [], bannerCoupons: [], bundlePromos: [], cart: loadSavedCart(), selectedLocation: null, shippingCost: 0, deliveryCovered: true, appliedCoupon: null }

function loadSavedCustomer() {
  try {
    const saved = JSON.parse(localStorage.getItem(CUSTOMER_KEY) || '{}')
    if (saved.name) elements.name.value = saved.name
    if (saved.phone) elements.phone.value = saved.phone
    if (saved.address) elements.address.value = saved.address
  } catch {}
}

function saveCustomer() {
  localStorage.setItem(CUSTOMER_KEY, JSON.stringify({
    name: elements.name.value.trim(),
    phone: elements.phone.value.trim(),
    address: elements.address.value.trim(),
  }))
}

const elements = {
  featuredBanner: document.getElementById('featured-banner'),
  featuredBannerTrack: document.getElementById('featured-banner-track'),
  featuredBannerDots: document.getElementById('featured-banner-dots'),
  productsGrid: document.getElementById('products-grid'),
  productSearch: document.getElementById('product-search'),
  cartItems: document.getElementById('cart-items'),
  productCount: document.getElementById('product-count'),
  subtotal: document.getElementById('subtotal'),
  shipping: document.getElementById('shipping'),
  bundleDiscountRow: document.getElementById('bundle-discount-row'),
  bundleDiscount: document.getElementById('bundle-discount'),
  discountRow: document.getElementById('discount-row'),
  discount: document.getElementById('discount'),
  couponCode: document.getElementById('coupon-code'),
  couponApplyBtn: document.getElementById('coupon-apply-btn'),
  couponMessage: document.getElementById('coupon-message'),
  total: document.getElementById('total'),
  address: document.getElementById('address'),
  name: document.getElementById('customer-name'),
  phone: document.getElementById('phone'),
  checkoutBtn: document.getElementById('checkout-btn'),
  addressHint: document.getElementById('address-hint'),
  cartPanel: document.getElementById('cart-panel'),
  cartBackdrop: document.getElementById('cart-backdrop'),
  cartClose: document.getElementById('cart-close'),
  cartFab: document.getElementById('cart-fab'),
  cartFabCount: document.getElementById('cart-fab-count'),
  cartFabTotal: document.getElementById('cart-fab-total'),
  deliveryMapBlock: document.getElementById('delivery-map-block'),
  addressLabel: document.getElementById('address-label'),
  cashBlock: document.getElementById('cash-block'),
  cashAmount: document.getElementById('cash-amount'),
  changeHint: document.getElementById('change-hint'),
  cashTotalHint: document.getElementById('cash-total-hint'),
  quickCashButtons: document.getElementById('quick-cash-buttons'),
  transferBlock: document.getElementById('transfer-block'),
  notes: document.getElementById('notes'),
  requestedTime: document.getElementById('requested-time'),
  outsideHoursHint: document.getElementById('outside-hours-hint'),
  navToggle: document.getElementById('nav-toggle'),
  navClose: document.getElementById('nav-close'),
  navBackdrop: document.getElementById('nav-backdrop'),
  navDrawer: document.getElementById('nav-drawer'),
  navLinks: document.getElementById('nav-links'),
  productModal: document.getElementById('product-modal'),
  productModalBackdrop: document.getElementById('product-modal-backdrop'),
  productModalClose: document.getElementById('product-modal-close'),
  productModalImage: document.getElementById('product-modal-image'),
  productModalName: document.getElementById('product-modal-name'),
  productModalDescription: document.getElementById('product-modal-description'),
  productModalPrice: document.getElementById('product-modal-price'),
  productModalAdd: document.getElementById('product-modal-add'),
  productModalOptions: document.getElementById('product-modal-options'),
  deliveryModeOptions: document.getElementById('delivery-mode-options'),
  minOrderHint: document.getElementById('min-order-hint'),
  prepTimeHint: document.getElementById('prep-time-hint'),
  upsellSuggestions: document.getElementById('upsell-suggestions'),
  confirmModal: document.getElementById('confirm-modal'),
  confirmModalBackdrop: document.getElementById('confirm-modal-backdrop'),
  confirmModalClose: document.getElementById('confirm-modal-close'),
  confirmSummary: document.getElementById('confirm-summary'),
  confirmError: document.getElementById('confirm-error'),
  confirmModalSend: document.getElementById('confirm-modal-send'),
  confirmModalEdit: document.getElementById('confirm-modal-edit'),
  giftInfo: document.getElementById('gift-info'),
  giftHint: document.getElementById('gift-hint'),
}

const MIN_DELIVERY_ORDER = elements.deliveryModeOptions
  ? Number(elements.deliveryModeOptions.dataset.minOrder) || null
  : null

const GIFT_THRESHOLD = elements.giftInfo ? Number(elements.giftInfo.dataset.threshold) || null : null
const GIFT_PRODUCT_NAME = elements.giftInfo ? elements.giftInfo.dataset.productName || null : null

const OPENS_AT = elements.requestedTime.dataset.opensAt || null
const CLOSES_AT = elements.requestedTime.dataset.closesAt || null
const ACCEPT_ORDERS_OUTSIDE_HOURS = elements.requestedTime.dataset.acceptOutsideHours === 'true'
const OUTSIDE_HOURS_WHATSAPP = elements.requestedTime.dataset.whatsappNumber || null

function isWithinBusinessHours(timeStr) {
  if (!OPENS_AT || !CLOSES_AT) return true
  if (OPENS_AT <= CLOSES_AT) return timeStr >= OPENS_AT && timeStr <= CLOSES_AT
  return timeStr >= OPENS_AT || timeStr <= CLOSES_AT
}

function getSantiagoTimeStr() {
  // Independent of the visitor's own device timezone/clock - always Santiago's, to
  // match what opens_at/closes_at and the server's own check are expressed in.
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/Santiago', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date())
}

function isOutsideHoursNow() {
  return Boolean(OPENS_AT && CLOSES_AT) && !isWithinBusinessHours(getSantiagoTimeStr())
}

function updateHoursGateHint() {
  const outsideNow = isOutsideHoursNow()
  elements.checkoutBtn.disabled = outsideNow && !ACCEPT_ORDERS_OUTSIDE_HOURS
  if (!elements.outsideHoursHint) return
  if (!outsideNow) {
    elements.outsideHoursHint.style.display = 'none'
    return
  }
  elements.outsideHoursHint.style.display = 'block'
  if (ACCEPT_ORDERS_OUTSIDE_HOURS) {
    elements.outsideHoursHint.dataset.variant = 'warning'
    elements.outsideHoursHint.textContent = `A esta hora solo puedes agendar. Nuestras entregas son de ${OPENS_AT} a ${CLOSES_AT}.`
  } else {
    elements.outsideHoursHint.dataset.variant = 'blocked'
    const contactLink = OUTSIDE_HOURS_WHATSAPP
      ? `<a href="https://wa.me/${OUTSIDE_HOURS_WHATSAPP}" target="_blank" rel="noopener">Escríbenos por WhatsApp</a> para coordinar.`
      : 'Escríbenos por WhatsApp para coordinar.'
    elements.outsideHoursHint.innerHTML = `Nuestro horario es de ${OPENS_AT} a ${CLOSES_AT}. ${contactLink}`
  }
}

function openNav() {
  elements.navDrawer.classList.add('open')
  elements.navBackdrop.classList.add('open')
  document.body.classList.add('nav-open')
}

function closeNav() {
  elements.navDrawer.classList.remove('open')
  elements.navBackdrop.classList.remove('open')
  document.body.classList.remove('nav-open')
}

let currentModalProduct = null

function optionInputName(group) {
  return `modal-option-group-${group.id}`
}

function renderModalOptions(product) {
  if (!hasOptionGroups(product)) {
    elements.productModalOptions.innerHTML = ''
    return
  }
  elements.productModalOptions.innerHTML = product.optionGroups.map((group) => `
    <div class="modal-option-group">
      <p class="modal-option-group-title">
        ${escapeHtml(group.name)} ${group.required ? '<span class="required-tag">obligatorio</span>' : ''}
      </p>
      ${group.options.map((option) => `
        <label class="modal-option">
          <input type="${group.multiSelect ? 'checkbox' : 'radio'}" name="${optionInputName(group)}"
                 value="${option.id}" data-price-delta="${option.priceDelta}">
          ${escapeHtml(option.name)} ${option.priceDelta ? `(+${formatPrice(option.priceDelta)})` : ''}
        </label>
      `).join('')}
    </div>
  `).join('')
}

function getModalSelectedOptions() {
  if (!currentModalProduct) return []
  const inputs = elements.productModalOptions.querySelectorAll('input:checked')
  return Array.from(inputs).map((input) => ({
    id: Number(input.value),
    priceDelta: Number(input.dataset.priceDelta) || 0,
    name: input.closest('.modal-option').textContent.trim().replace(/\s*\(\+.*\)$/, ''),
  }))
}

function updateModalPrice() {
  if (!currentModalProduct) return
  const extra = getModalSelectedOptions().reduce((sum, o) => sum + o.priceDelta, 0)
  // The struck-through "before" price only makes sense with no extras added yet - once the
  // customer picks a paid option, showing a plain total is clearer than mixing both.
  elements.productModalPrice.innerHTML = extra === 0
    ? priceHtml(currentModalProduct)
    : formatPrice(currentModalProduct.price + extra)
}

function openProductModal(productId) {
  const product = STATE.products.find((item) => item.id === Number(productId))
  if (!product) return
  currentModalProduct = product
  elements.productModalName.textContent = product.name
  elements.productModalDescription.textContent = product.description || ''
  renderModalOptions(product)
  updateModalPrice()
  if (product.soldOut) {
    elements.productModalAdd.disabled = true
    elements.productModalAdd.textContent = 'Agotado'
  } else {
    elements.productModalAdd.disabled = false
    elements.productModalAdd.textContent = 'Agregar'
  }
  if (product.imageUrl) {
    elements.productModalImage.src = product.imageUrl
    elements.productModalImage.style.display = 'block'
  } else {
    elements.productModalImage.style.display = 'none'
  }
  elements.productModal.classList.add('open')
  elements.productModalBackdrop.classList.add('open')
  document.body.classList.add('modal-open')
}

function handleModalAddClick() {
  if (!currentModalProduct || currentModalProduct.soldOut) return
  for (const group of currentModalProduct.optionGroups || []) {
    const chosen = elements.productModalOptions.querySelectorAll(`input[name="${optionInputName(group)}"]:checked`)
    if (group.required && chosen.length === 0) {
      alert(`Elige una opción para "${group.name}".`)
      return
    }
  }
  addToCart(currentModalProduct.id, getModalSelectedOptions())
  openCart()
  closeProductModal()
}

function closeProductModal() {
  elements.productModal.classList.remove('open')
  elements.productModalBackdrop.classList.remove('open')
  document.body.classList.remove('modal-open')
}

function openCart() {
  elements.cartPanel.classList.add('open')
  elements.cartBackdrop.classList.add('open')
  document.body.classList.add('cart-open')
}

function closeCart() {
  elements.cartPanel.classList.remove('open')
  elements.cartBackdrop.classList.remove('open')
  document.body.classList.remove('cart-open')
}

function initCartSwipeToClose() {
  const panel = elements.cartPanel
  const isMobileLayout = () => window.matchMedia('(max-width: 940px)').matches
  let startY = 0
  let currentY = 0
  let dragging = false

  panel.addEventListener('touchstart', (event) => {
    // Only from the top of the sheet - a scrolled-down product list shouldn't hijack the drag.
    if (!isMobileLayout() || !panel.classList.contains('open') || panel.scrollTop > 0) return
    startY = event.touches[0].clientY
    currentY = startY
    dragging = true
    panel.style.transition = 'none'
  }, { passive: true })

  panel.addEventListener('touchmove', (event) => {
    if (!dragging) return
    currentY = event.touches[0].clientY
    const delta = currentY - startY
    if (delta > 0) panel.style.transform = `translateY(${delta}px)`
  }, { passive: true })

  panel.addEventListener('touchend', () => {
    if (!dragging) return
    dragging = false
    panel.style.transition = ''
    panel.style.transform = ''
    if (currentY - startY > 80) closeCart()
  })
}

let map, marker, suggestions = []

function saveCart() {
  localStorage.setItem(CART_KEY, JSON.stringify(STATE.cart))
  clearAppliedCoupon()
}

function clearAppliedCoupon(message) {
  if (!STATE.appliedCoupon) return
  STATE.appliedCoupon = null
  if (elements.couponMessage) {
    elements.couponMessage.textContent = message || 'Tu carrito cambió, vuelve a aplicar el cupón.'
    elements.couponMessage.className = 'coupon-message coupon-message-info'
  }
}

async function applyCoupon() {
  const code = elements.couponCode.value.trim()
  if (!code) return
  elements.couponApplyBtn.disabled = true
  elements.couponApplyBtn.textContent = 'Aplicando...'
  elements.couponMessage.textContent = ''

  const deliveryMode = getDeliveryMode()
  try {
    const response = await fetch('/api/apply-coupon', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        phone: elements.phone.value.trim(),
        deliveryMode,
        items: STATE.cart.map((item) => ({
          id: item.id,
          quantity: item.quantity,
          options: (item.selectedOptions || []).map((o) => o.id),
        })),
        lat: deliveryMode === 'envio' && STATE.selectedLocation ? STATE.selectedLocation.lat : null,
        lng: deliveryMode === 'envio' && STATE.selectedLocation ? STATE.selectedLocation.lng : null,
      }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok || !data.ok) {
      STATE.appliedCoupon = null
      elements.couponMessage.textContent = data.message || 'No se pudo aplicar el cupón.'
      elements.couponMessage.className = 'coupon-message coupon-message-error'
    } else {
      STATE.appliedCoupon = { code: data.code, discountPercent: data.discountPercent, scope: data.scope, discountAmount: data.discountAmount }
      elements.couponMessage.textContent = `Cupón ${data.code} aplicado: -${formatPrice(data.discountAmount)}`
      elements.couponMessage.className = 'coupon-message coupon-message-ok'
    }
  } catch (error) {
    STATE.appliedCoupon = null
    elements.couponMessage.textContent = 'No se pudo conectar con el servidor. Intenta de nuevo.'
    elements.couponMessage.className = 'coupon-message coupon-message-error'
  }

  elements.couponApplyBtn.disabled = false
  elements.couponApplyBtn.textContent = 'Aplicar'
  updateSummary()
}

function formatPrice(value) {
  return `$${Number(value).toLocaleString('es-CL')}`
}

function priceHtml(product) {
  if (!product.originalPrice || product.originalPrice <= product.price) return formatPrice(product.price)
  return `<s class="original-price">${formatPrice(product.originalPrice)}</s> ${formatPrice(product.price)}`
}

// Product/category names come from the admin panel, not from the customer, but they still
// end up inside innerHTML on the public menu - escape them so an admin/staff account can't
// (accidentally or otherwise) inject markup that runs in every visitor's browser.
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char])
}

function getDeliveryMode() {
  return document.querySelector('input[name="delivery-mode"]:checked')?.value || 'retira'
}

function getPaymentMethod() {
  return document.querySelector('input[name="payment-method"]:checked')?.value || 'efectivo'
}

function toggleDeliveryFields() {
  const isDelivery = getDeliveryMode() === 'envio'
  // The address input itself stays visible in both modes - in retiro it's an
  // optional plain text field (no map needed, the customer picks it up in person);
  // in despacho it's required and paired with the map/pin for shipping cost.
  elements.addressLabel.textContent = isDelivery ? 'Dirección' : 'Dirección (opcional — para futuros despachos)'
  elements.deliveryMapBlock.style.display = isDelivery ? 'grid' : 'none'
  // The map was created while its container may have been hidden (display:none),
  // so Leaflet needs a nudge to recompute its size once it becomes visible.
  if (isDelivery && map) setTimeout(() => map.invalidateSize(), 0)
}

function getRequestedTime() {
  return elements.requestedTime.value || null
}

function togglePaymentFields() {
  const method = getPaymentMethod()
  elements.cashBlock.style.display = method === 'efectivo' ? 'grid' : 'none'
  if (elements.transferBlock) {
    elements.transferBlock.style.display = method === 'transferencia' ? 'block' : 'none'
  }
  updateChangeHint()
}

function computeBundleDiscount() {
  let total = 0
  STATE.bundlePromos.forEach((promo) => {
    const unitPrices = []
    STATE.cart.forEach((item) => {
      if (promo.productIds.includes(item.id)) {
        for (let i = 0; i < item.quantity; i++) unitPrices.push(item.price)
      }
    })
    if (unitPrices.length < promo.buyQuantity) return

    unitPrices.sort((a, b) => b - a)
    const freeQuantity = promo.buyQuantity - promo.payQuantity
    const numFullGroups = Math.floor(unitPrices.length / promo.buyQuantity)
    for (let group = 0; group < numFullGroups; group++) {
      const start = group * promo.buyQuantity
      const chunk = unitPrices.slice(start, start + promo.buyQuantity)
      if (freeQuantity > 0) total += chunk.slice(-freeQuantity).reduce((sum, price) => sum + price, 0)
    }
  })
  return Math.round(total)
}

function getOrderTotal() {
  const subtotal = STATE.cart.reduce((sum, item) => sum + item.price * item.quantity, 0)
  const wantsDelivery = getDeliveryMode() === 'envio' && STATE.selectedLocation
  const shipping = wantsDelivery && STATE.deliveryCovered ? STATE.shippingCost : 0
  const bundleDiscount = computeBundleDiscount()
  const discount = STATE.appliedCoupon ? STATE.appliedCoupon.discountAmount : 0
  return Math.max(0, subtotal + shipping - bundleDiscount - discount)
}

function getQuickCashAmounts(total) {
  if (total <= 0) return []
  const exact = Math.ceil(total)
  const nextThousand = Math.ceil(exact / 1000) * 1000
  const bills = [2000, 5000, 10000, 20000, 50000].filter((bill) => bill > nextThousand).slice(0, 2)
  return [...new Set([exact, nextThousand, ...bills])].sort((a, b) => a - b).slice(0, 4)
}

function renderQuickCashButtons(total) {
  const amounts = getQuickCashAmounts(total)
  elements.quickCashButtons.innerHTML = amounts.map((amount) => `
    <label class="quick-cash-option" data-amount="${amount}">${amount === Math.ceil(total) ? `Exacto ${formatPrice(amount)}` : formatPrice(amount)}</label>
  `).join('')
}

function updateChangeHint() {
  if (getPaymentMethod() !== 'efectivo') return
  const totalValue = getOrderTotal()
  elements.cashTotalHint.textContent = `Total a pagar: ${formatPrice(totalValue)}`
  renderQuickCashButtons(totalValue)

  const cash = Number(elements.cashAmount.value)
  if (!cash) {
    elements.changeHint.textContent = ''
    return
  }
  if (cash < totalValue) {
    elements.changeHint.textContent = `Falta ${formatPrice(totalValue - cash)} para cubrir el total.`
  } else {
    elements.changeHint.textContent = `Vuelto: ${formatPrice(cash - totalValue)}`
  }
}

async function fetchShippingCost(lat, lng) {
  try {
    const res = await fetch('/api/shipping-cost', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat, lng }),
    })
    const data = await res.json()
    // shippingCost is null when the address isn't covered - don't collapse that to 0.
    return { covered: !!data.covered, shippingCost: data.covered ? data.shippingCost : null }
  } catch (error) {
    return { covered: false, shippingCost: null }
  }
}

function groupProducts(products) {
  const categories = []
  const categoryIndex = new Map()

  products.forEach((product) => {
    let category = categoryIndex.get(product.categoryId)
    if (!category) {
      category = { id: product.categoryId, name: product.category, subcategories: [], subcategoryIndex: new Map() }
      categoryIndex.set(product.categoryId, category)
      categories.push(category)
    }

    const subKey = product.subcategoryId || 'none'
    let subcategory = category.subcategoryIndex.get(subKey)
    if (!subcategory) {
      subcategory = { id: product.subcategoryId, name: product.subcategory, products: [] }
      category.subcategoryIndex.set(subKey, subcategory)
      category.subcategories.push(subcategory)
    }
    subcategory.products.push(product)
  })

  return categories
}

function findBundlePromoForProduct(product) {
  return STATE.bundlePromos.find((promo) => promo.productIds.includes(product.id))
}

function productCardHtml(product) {
  const soldOut = product.soldOut
  const badge = soldOut
    ? '<span class="sold-out-badge">Agotado</span>'
    : (product.featured ? '<span class="featured-badge">⭐ Recomendado</span>' : '')
  const safeName = escapeHtml(product.name)
  const bundlePromo = !soldOut ? findBundlePromoForProduct(product) : null
  return `
    <article class="product-card${soldOut ? ' sold-out' : ''}">
      ${product.imageUrl
        ? `<div class="product-photo-wrap"><img src="${product.imageUrl}" alt="${safeName}" class="product-photo">${badge}</div>`
        : ''}
      <div>
        ${!product.imageUrl ? badge : ''}
        <strong>${safeName}</strong>
        <div class="price">${priceHtml(product)}</div>
        ${product.prepMinutes ? `<span class="prep-time">⏱ ${product.prepMinutes} min</span>` : ''}
        ${bundlePromo ? `<span class="bundle-badge">Lleva ${bundlePromo.buyQuantity}, paga ${bundlePromo.payQuantity}</span>` : ''}
      </div>
      <div class="card-actions">
        <button type="button" class="details-btn" data-details="${product.id}" aria-label="Ver detalle">ⓘ</button>
        ${soldOut
          ? '<button type="button" class="sold-out-btn" disabled>Agotado</button>'
          : hasOptionGroups(product)
            ? `<button type="button" class="add-btn" data-details="${product.id}" aria-label="Elegir ${safeName}">+</button>`
            : `<button type="button" class="add-btn" data-add="${product.id}" aria-label="Agregar ${safeName}">+</button>`}
      </div>
    </article>
  `
}

function hasOptionGroups(product) {
  return Array.isArray(product.optionGroups) && product.optionGroups.length > 0
}

function renderNav(categories) {
  elements.navLinks.innerHTML = categories.map((category) => `
    <div class="nav-category">
      <button type="button" class="nav-category-link" data-target="cat-${category.id}">${escapeHtml(category.name)}</button>
      ${category.subcategories.filter((sub) => sub.name).map((sub) => `
        <button type="button" class="nav-subcategory-link" data-target="sub-${category.id}-${sub.id}">${escapeHtml(sub.name)}</button>
      `).join('')}
    </div>
  `).join('')
}

function renderProductGrid(filterTerm = '') {
  const term = filterTerm.trim().toLowerCase()
  const filtered = term ? STATE.products.filter((product) => product.name.toLowerCase().includes(term)) : STATE.products

  if (!filtered.length) {
    elements.productsGrid.innerHTML = `<p class="hint">${term ? 'No se encontraron productos con ese nombre.' : 'No hay productos disponibles.'}</p>`
    return
  }

  const categories = groupProducts(filtered)
  elements.productsGrid.innerHTML = categories.map((category) => `
    <section class="menu-section" id="cat-${category.id}">
      <h2 class="menu-section-title">${escapeHtml(category.name)}</h2>
      ${category.subcategories.map((sub) => `
        <div class="menu-subsection" id="sub-${category.id}-${sub.id || 'none'}">
          ${sub.name ? `<h3 class="menu-subsection-title">${escapeHtml(sub.name)}</h3>` : ''}
          <div class="products-grid">${sub.products.map(productCardHtml).join('')}</div>
        </div>
      `).join('')}
    </section>
  `).join('')
}

function renderProducts() {
  elements.productCount.textContent = STATE.products.length
  renderFeaturedBanner()
  if (!STATE.products.length) {
    elements.productsGrid.innerHTML = '<p class="hint">No hay productos disponibles.</p>'
    elements.navLinks.innerHTML = ''
    return
  }

  renderNav(groupProducts(STATE.products))
  renderProductGrid(elements.productSearch.value)
}

let featuredBannerTimer = null
let featuredBannerIndex = 0
let featuredBannerSlideCount = 0

function goToFeaturedSlide(index) {
  featuredBannerIndex = index
  elements.featuredBannerTrack.style.transform = `translateX(-${index * 100}%)`
  elements.featuredBannerDots.querySelectorAll('.featured-dot').forEach((dot, dotIndex) => {
    dot.classList.toggle('active', dotIndex === index)
  })
}

function startFeaturedBannerAutoplay() {
  clearInterval(featuredBannerTimer)
  featuredBannerTimer = featuredBannerSlideCount > 1
    ? setInterval(() => goToFeaturedSlide((featuredBannerIndex + 1) % featuredBannerSlideCount), 5000)
    : null
}

function initFeaturedBannerSwipe() {
  const track = elements.featuredBannerTrack
  let startX = 0
  let currentX = 0
  let dragging = false
  let containerWidth = 0

  track.addEventListener('touchstart', (event) => {
    if (featuredBannerSlideCount < 2) return
    startX = event.touches[0].clientX
    currentX = startX
    dragging = true
    containerWidth = elements.featuredBanner.offsetWidth || 1
    clearInterval(featuredBannerTimer)
    track.style.transition = 'none'
  }, { passive: true })

  track.addEventListener('touchmove', (event) => {
    if (!dragging) return
    currentX = event.touches[0].clientX
    const deltaPercent = ((currentX - startX) / containerWidth) * 100
    track.style.transform = `translateX(calc(-${featuredBannerIndex * 100}% + ${deltaPercent}%))`
  }, { passive: true })

  track.addEventListener('touchend', () => {
    if (!dragging) return
    dragging = false
    track.style.transition = ''
    const deltaX = currentX - startX
    const threshold = containerWidth * 0.15
    if (deltaX < -threshold && featuredBannerIndex < featuredBannerSlideCount - 1) {
      goToFeaturedSlide(featuredBannerIndex + 1)
    } else if (deltaX > threshold && featuredBannerIndex > 0) {
      goToFeaturedSlide(featuredBannerIndex - 1)
    } else {
      goToFeaturedSlide(featuredBannerIndex)
    }
    startFeaturedBannerAutoplay()
  })
}

function formatDateDMY(isoDate) {
  const [year, month, day] = isoDate.split('-')
  return `${day}-${month}-${year}`
}

function productSlideHtml(product) {
  return `
    <button type="button" class="featured-slide" data-details="${product.id}">
      ${product.imageUrl ? `<img src="${product.imageUrl}" alt="${escapeHtml(product.name)}" class="featured-slide-photo">` : ''}
      <div class="featured-slide-info">
        <span class="featured-slide-label">⭐ Recomendado</span>
        <strong>${escapeHtml(product.name)}</strong>
        <div class="featured-slide-price">${priceHtml(product)}</div>
      </div>
    </button>
  `
}

function couponSlideHtml(coupon) {
  const validityText = coupon.validUntil ? `Válido hasta ${formatDateDMY(coupon.validUntil)}` : ''
  const scopeText = coupon.scope === 'order' ? 'En toda tu compra' : 'En productos seleccionados'
  const safeCode = escapeHtml(coupon.code)

  if (coupon.bannerImageUrl) {
    return `
      <button type="button" class="featured-slide featured-slide-coupon" data-coupon-code="${safeCode}">
        <img src="${coupon.bannerImageUrl}" alt="${safeCode}" class="featured-slide-photo">
        <div class="featured-slide-info">
          <span class="featured-slide-label">🏷️ Cupón</span>
          <strong>${coupon.discountPercent}% OFF con ${safeCode}</strong>
          ${validityText ? `<div class="featured-slide-price">${validityText}</div>` : ''}
        </div>
      </button>
    `
  }
  return `
    <button type="button" class="featured-slide featured-slide-coupon-auto" data-coupon-code="${safeCode}">
      <div class="coupon-slide-badge">-${coupon.discountPercent}%</div>
      <div class="featured-slide-info">
        <span class="featured-slide-label">🏷️ Usa el código</span>
        <strong>${safeCode}</strong>
        <div class="featured-slide-price">${scopeText}${validityText ? ' · ' + validityText : ''}</div>
      </div>
    </button>
  `
}

function renderFeaturedBanner() {
  if (!elements.featuredBanner) return
  const couponSlides = STATE.bannerCoupons.map(couponSlideHtml)
  const productSlides = STATE.products.filter((product) => product.featured && !product.soldOut).map(productSlideHtml)
  const slides = [...couponSlides, ...productSlides]

  clearInterval(featuredBannerTimer)
  featuredBannerSlideCount = slides.length

  if (!slides.length) {
    elements.featuredBanner.hidden = true
    elements.featuredBannerTrack.innerHTML = ''
    elements.featuredBannerDots.innerHTML = ''
    return
  }

  elements.featuredBanner.hidden = false
  elements.featuredBannerTrack.innerHTML = slides.join('')

  elements.featuredBannerDots.innerHTML = slides.length > 1
    ? slides.map((_, index) => `<button type="button" class="featured-dot" data-slide="${index}" aria-label="Ir a la promoción ${index + 1}"></button>`).join('')
    : ''

  goToFeaturedSlide(0)
  startFeaturedBannerAutoplay()
}

function getUpsellSuggestions(limit = 2) {
  const cartIds = new Set(STATE.cart.map((item) => item.id))
  const candidates = STATE.products.filter((product) => !product.soldOut && !cartIds.has(product.id))
  const featured = candidates.filter((product) => product.featured)
  const rest = candidates.filter((product) => !product.featured)
  return [...featured, ...rest].slice(0, limit)
}

function renderUpsellSuggestions() {
  if (!elements.upsellSuggestions) return
  if (!STATE.cart.length) {
    elements.upsellSuggestions.innerHTML = ''
    return
  }
  const suggestions = getUpsellSuggestions()
  if (!suggestions.length) {
    elements.upsellSuggestions.innerHTML = ''
    return
  }
  elements.upsellSuggestions.innerHTML = `
    <p class="hint">También te podría interesar</p>
    <div class="upsell-list">
      ${suggestions.map((product) => `
        <div class="upsell-item">
          <span>${escapeHtml(product.name)}</span>
          <span class="upsell-price">${priceHtml(product)}</span>
          ${hasOptionGroups(product)
            ? `<button type="button" data-details="${product.id}" aria-label="Elegir ${escapeHtml(product.name)}">+</button>`
            : `<button type="button" data-add="${product.id}" aria-label="Agregar ${escapeHtml(product.name)}">+</button>`}
        </div>
      `).join('')}
    </div>
  `
}

function renderCart() {
  const cart = STATE.cart
  if (!cart.length) {
    elements.cartItems.innerHTML = '<p class="hint">Aún no hay productos en el carrito.</p>'
  } else {
    elements.cartItems.innerHTML = cart.map((item) => `
      <article class="cart-item">
        <div>
          <strong>${escapeHtml(item.name)}</strong>
          ${item.selectedOptions && item.selectedOptions.length
            ? `<small class="cart-item-options">${item.selectedOptions.map((o) => escapeHtml(o.name)).join(', ')}</small>`
            : ''}
          <small>${formatPrice(item.price)} c/u</small>
        </div>
        <div class="cart-item-controls">
          <div>
            <button type="button" class="qty-btn" data-decrement="${item.cartKey}" aria-label="Restar ${escapeHtml(item.name)}">−</button>
            <span class="qty-value">${item.quantity}</span>
            <button type="button" class="qty-btn" data-increment="${item.cartKey}" aria-label="Sumar ${escapeHtml(item.name)}">+</button>
          </div>
          <button type="button" class="remove-btn" data-remove="${item.cartKey}" aria-label="Quitar ${escapeHtml(item.name)}">Quitar</button>
        </div>
      </article>
    `).join('')
  }
  renderUpsellSuggestions()
  updateSummary()
}

function giftIsReached(total) {
  return Boolean(GIFT_THRESHOLD && GIFT_PRODUCT_NAME && STATE.cart.length && total >= GIFT_THRESHOLD)
}

function updateGiftHint(total) {
  if (!elements.giftHint || !GIFT_THRESHOLD || !GIFT_PRODUCT_NAME) return
  if (!STATE.cart.length) {
    elements.giftHint.hidden = true
    return
  }
  if (total >= GIFT_THRESHOLD) {
    elements.giftHint.textContent = `🎁 ¡Llevas de regalo: ${GIFT_PRODUCT_NAME}!`
    elements.giftHint.hidden = false
  } else {
    elements.giftHint.textContent = `Agrega ${formatPrice(GIFT_THRESHOLD - total)} más y llévate de regalo: ${GIFT_PRODUCT_NAME}`
    elements.giftHint.hidden = false
  }
}

function updateSummary() {
  const subtotal = STATE.cart.reduce((sum, item) => sum + item.price * item.quantity, 0)
  const wantsDelivery = getDeliveryMode() === 'envio' && STATE.selectedLocation
  const outOfCoverage = wantsDelivery && !STATE.deliveryCovered
  const shipping = wantsDelivery && STATE.deliveryCovered ? STATE.shippingCost : 0
  const bundleDiscount = computeBundleDiscount()
  const discount = STATE.appliedCoupon ? STATE.appliedCoupon.discountAmount : 0
  const total = Math.max(0, subtotal + shipping - bundleDiscount - discount)

  elements.subtotal.textContent = formatPrice(subtotal)
  elements.shipping.textContent = outOfCoverage ? 'Sin cobertura' : formatPrice(shipping)
  if (elements.bundleDiscountRow) elements.bundleDiscountRow.hidden = !bundleDiscount
  if (elements.bundleDiscount) elements.bundleDiscount.textContent = `-${formatPrice(bundleDiscount)}`
  if (elements.discountRow) elements.discountRow.hidden = !discount
  if (elements.discount) elements.discount.textContent = `-${formatPrice(discount)}`
  elements.total.textContent = outOfCoverage ? '—' : formatPrice(total)
  updateGiftHint(total)

  const itemCount = STATE.cart.reduce((sum, item) => sum + item.quantity, 0)
  elements.cartFabCount.textContent = itemCount
  elements.cartFabTotal.textContent = outOfCoverage ? formatPrice(subtotal) : formatPrice(total)

  updateMinOrderHint(subtotal)
  updatePrepTimeHint()
  updateChangeHint()
}

function getMinOrderShortfall(subtotal) {
  if (getDeliveryMode() !== 'envio' || !MIN_DELIVERY_ORDER) return 0
  return Math.max(0, MIN_DELIVERY_ORDER - subtotal)
}

function updateMinOrderHint(subtotal) {
  if (!elements.minOrderHint) return
  const shortfall = getMinOrderShortfall(subtotal)
  if (!shortfall) {
    elements.minOrderHint.style.display = 'none'
    return
  }
  elements.minOrderHint.style.display = 'block'
  elements.minOrderHint.textContent = `Pedido mínimo para despacho: ${formatPrice(MIN_DELIVERY_ORDER)} (te faltan ${formatPrice(shortfall)}).`
}

function getCartMaxPrepMinutes() {
  // The slowest product sets the pace, not the sum - two items being prepared at the
  // same time don't take longer together than the slower one alone (no parallelism
  // accounting yet, that's future work).
  return STATE.cart.reduce((max, item) => {
    const product = STATE.products.find((p) => p.id === item.id)
    const prepMinutes = product ? product.prepMinutes : null
    return prepMinutes && prepMinutes > max ? prepMinutes : max
  }, 0)
}

function updatePrepTimeHint() {
  if (!elements.prepTimeHint) return
  const maxPrepMinutes = getCartMaxPrepMinutes()
  if (!maxPrepMinutes) {
    elements.prepTimeHint.style.display = 'none'
    return
  }
  elements.prepTimeHint.style.display = 'block'
  elements.prepTimeHint.textContent = `Preparación: ≈${maxPrepMinutes} min. Elige un horario que lo tenga en cuenta.`
}

async function setLocation(lat, lng, label, precise = true) {
  STATE.selectedLocation = { lat, lng, label }
  if (marker) {
    marker.setLatLng([lat, lng])
    map.setView([lat, lng], 16)
  }
  elements.addressHint.textContent = `Buscando costo de envío para: ${label}...`

  const { covered, shippingCost } = await fetchShippingCost(lat, lng)
  STATE.shippingCost = shippingCost
  STATE.deliveryCovered = covered
  clearAppliedCoupon()
  const baseMessage = covered
    ? `Dirección confirmada: ${label}`
    : `${label} está fuera de nuestra zona de reparto. Elige "Retiro" o prueba otra dirección.`
  const precisionWarning = precise ? '' : ' ⚠️ Esta búsqueda no incluye el número exacto: arrastra el pin 🛵 hasta tu ubicación real.'
  elements.addressHint.textContent = baseMessage + precisionWarning
  updateSummary()
}

async function loadProducts() {
  try {
    const resp = await fetch('/api/products')
    if (!resp.ok) throw new Error('Fetch failed')
    STATE.products = await resp.json()
  } catch (error) {
    STATE.products = []
    elements.productsGrid.innerHTML = '<p class="hint">No se pudieron cargar los productos.</p>'
  }

  try {
    const resp = await fetch('/api/banner-coupons')
    STATE.bannerCoupons = resp.ok ? await resp.json() : []
  } catch (error) {
    STATE.bannerCoupons = []
  }

  try {
    const resp = await fetch('/api/bundle-promos')
    STATE.bundlePromos = resp.ok ? await resp.json() : []
  } catch (error) {
    STATE.bundlePromos = []
  }

  renderProducts()
  // A cart restored from localStorage is rendered once, synchronously, before this
  // fetch resolves (STATE.products is still [] at that point) - anything in the cart
  // summary that looks a cart item back up against STATE.products (prep time, upsell
  // suggestions) silently comes up empty on that first pass and never recovers unless
  // the cart is re-rendered here, now that STATE.products is actually populated.
  renderCart()
}

const DELIVERY_ICON = L.divIcon({
  html: '<div class="delivery-pin">🛵</div>',
  className: '',
  iconSize: [36, 36],
  iconAnchor: [18, 34],
})

function startMap() {
  const mapEl = document.getElementById('map')
  const startLat = Number(mapEl.dataset.lat) || -33.4489
  const startLng = Number(mapEl.dataset.lng) || -70.6693
  map = L.map('map').setView([startLat, startLng], 14)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map)
  marker = L.marker([startLat, startLng], { icon: DELIVERY_ICON, draggable: true }).addTo(map)
  marker.on('dragend', () => {
    const pos = marker.getLatLng()
    setLocationFromPin(pos.lat, pos.lng)
  })
  map.on('click', (e) => {
    setLocationFromPin(e.latlng.lat, e.latlng.lng)
  })
}

async function setLocationFromPin(lat, lng) {
  elements.addressHint.textContent = 'Buscando la dirección de este punto...'
  const reverseLabel = await reverseGeocode(lat, lng)
  const currentText = elements.address.value.trim()
  const typedNumber = extractHouseNumber(currentText)
  // Reverse geocoding often can't confirm a house number either - if the customer
  // already typed one, don't erase it just because they nudged the pin.
  const numberMissing = typedNumber && !reverseLabel.includes(typedNumber)
  const label = numberMissing ? currentText : reverseLabel
  elements.address.value = label
  await setLocation(lat, lng, label)
}

async function reverseGeocode(lat, lng) {
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`)
    const data = await res.json()
    return data.display_name || 'Ubicación seleccionada en el mapa'
  } catch {
    return 'Ubicación seleccionada en el mapa'
  }
}

function extractHouseNumber(text) {
  const match = (text || '').match(/\d+/)
  return match ? match[0] : null
}

async function searchAddress(query) {
  if (!query || query.length < 4) return []
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&q=${encodeURIComponent(query)}`)
    const data = await res.json()
    return data.slice(0, 6)
  } catch {
    return []
  }
}

function renderSuggestions(results) {
  const menu = document.querySelector('.suggestions-list')
  if (!menu) return
  if (!results.length) {
    menu.innerHTML = '<li class="suggestion-item">No se encontraron direcciones</li>'
    return
  }
  menu.innerHTML = results.map((item) => {
    const precise = !!(item.address && item.address.house_number)
    return `
    <li class="suggestion-item" data-lat="${item.lat}" data-lon="${item.lon}" data-display="${item.display_name}" data-precise="${precise}">
      ${item.display_name}${precise ? '' : ' <small>(aproximada, sin número)</small>'}
    </li>
  `
  }).join('')
}

function addToCart(productId, selectedOptions = []) {
  const product = STATE.products.find((item) => item.id === Number(productId))
  if (!product) return
  const sortedOptions = [...selectedOptions].sort((a, b) => a.id - b.id)
  const cartKey = `${product.id}:${sortedOptions.map((o) => o.id).join(',')}`
  const unitPrice = product.price + sortedOptions.reduce((sum, o) => sum + o.priceDelta, 0)

  const existing = STATE.cart.find((item) => item.cartKey === cartKey)
  if (existing) {
    existing.quantity += 1
  } else {
    STATE.cart.push({
      cartKey, id: product.id, name: product.name, price: unitPrice, quantity: 1,
      selectedOptions: sortedOptions.map((o) => ({ id: o.id, name: o.name })),
    })
  }
  saveCart()
  renderCart()
}

function removeFromCart(cartKey) {
  STATE.cart = STATE.cart.filter((item) => item.cartKey !== cartKey)
  saveCart()
  renderCart()
}

function incrementCartItem(cartKey) {
  const item = STATE.cart.find((cartItem) => cartItem.cartKey === cartKey)
  if (!item) return
  item.quantity += 1
  saveCart()
  renderCart()
}

function decrementCartItem(cartKey) {
  const item = STATE.cart.find((cartItem) => cartItem.cartKey === cartKey)
  if (!item) return
  item.quantity -= 1
  if (item.quantity <= 0) {
    STATE.cart = STATE.cart.filter((cartItem) => cartItem.cartKey !== cartKey)
  }
  saveCart()
  renderCart()
}

const PAYMENT_METHOD_LABELS = { efectivo: 'Efectivo', transferencia: 'Transferencia', tarjeta: 'Tarjeta al recibir' }

function buildWhatsAppText() {
  const name = elements.name.value.trim() || 'Cliente'
  const phone = elements.phone.value.trim() || 'Sin teléfono'
  const deliveryMode = getDeliveryMode()
  const paymentMethod = getPaymentMethod()
  const address = elements.address.value.trim() || 'Dirección no definida'
  const notes = elements.notes.value.trim()
  const shipping = deliveryMode === 'envio' && STATE.selectedLocation && STATE.deliveryCovered ? STATE.shippingCost : 0
  const total = getOrderTotal()
  const lines = [
    'Hola! Quiero hacer un pedido desde el menú digital:',
    `Nombre: ${name}`,
    `Teléfono: ${phone}`,
    `Tipo: ${deliveryMode === 'envio' ? 'Despacho' : 'Retiro'}`,
  ]
  if (deliveryMode === 'envio') lines.push(`Dirección: ${address}`)
  lines.push(`Pago: ${PAYMENT_METHOD_LABELS[paymentMethod] || paymentMethod}`)
  if (paymentMethod === 'efectivo' && Number(elements.cashAmount.value) > 0) {
    const cash = Number(elements.cashAmount.value)
    lines.push(cash >= total ? `Paga con: ${formatPrice(cash)} (vuelto ${formatPrice(cash - total)})` : `Paga con: ${formatPrice(cash)}`)
  }
  lines.push(`Hora sugerida: ${getRequestedTime() || 'No indicada'}`)
  if (notes) lines.push(`Notas: ${notes}`)
  lines.push('', 'Productos:')
  STATE.cart.forEach((item) => {
    const optionsText = item.selectedOptions && item.selectedOptions.length
      ? ` (${item.selectedOptions.map((o) => o.name).join(', ')})`
      : ''
    lines.push(`• ${item.quantity}× ${item.name}${optionsText} - ${formatPrice(item.price * item.quantity)}`)
  })
  lines.push('', `Subtotal: ${formatPrice(STATE.cart.reduce((sum, item) => sum + item.price * item.quantity, 0))}`)
  if (deliveryMode === 'envio') lines.push(`Envío: ${formatPrice(shipping)}`)
  const bundleDiscount = computeBundleDiscount()
  if (bundleDiscount) lines.push(`2x1/3x2 aplicado: -${formatPrice(bundleDiscount)}`)
  if (STATE.appliedCoupon) lines.push(`Descuento (${STATE.appliedCoupon.code}): -${formatPrice(STATE.appliedCoupon.discountAmount)}`)
  if (giftIsReached(total)) lines.push(`Regalo: ${GIFT_PRODUCT_NAME} (por compra sobre ${formatPrice(GIFT_THRESHOLD)})`)
  lines.push(`Total: ${formatPrice(total)}`)
  lines.push('', 'Gracias!')
  return encodeURIComponent(lines.join('\n'))
}

function buildConfirmSummaryHtml() {
  const name = elements.name.value.trim() || 'Cliente'
  const phone = elements.phone.value.trim() || 'Sin teléfono'
  const deliveryMode = getDeliveryMode()
  const paymentMethod = getPaymentMethod()
  const address = elements.address.value.trim()
  const notes = elements.notes.value.trim()
  const shipping = deliveryMode === 'envio' && STATE.selectedLocation && STATE.deliveryCovered ? STATE.shippingCost : 0
  const subtotal = STATE.cart.reduce((sum, item) => sum + item.price * item.quantity, 0)
  const total = getOrderTotal()

  const itemsHtml = STATE.cart.map((item) => {
    const optionsText = item.selectedOptions && item.selectedOptions.length
      ? ` <small>(${item.selectedOptions.map((o) => escapeHtml(o.name)).join(', ')})</small>`
      : ''
    return `<div class="confirm-row"><span>${item.quantity}× ${escapeHtml(item.name)}${optionsText}</span><span>${formatPrice(item.price * item.quantity)}</span></div>`
  }).join('')

  let paymentLine = PAYMENT_METHOD_LABELS[paymentMethod] || paymentMethod
  if (paymentMethod === 'efectivo' && Number(elements.cashAmount.value) > 0) {
    const cash = Number(elements.cashAmount.value)
    paymentLine += cash >= total ? ` - paga con ${formatPrice(cash)} (vuelto ${formatPrice(cash - total)})` : ` - paga con ${formatPrice(cash)}`
  }

  return `
    <p class="confirm-section-title">Tus datos</p>
    <div class="confirm-row"><span>Nombre</span><span>${escapeHtml(name)}</span></div>
    <div class="confirm-row"><span>Teléfono</span><span>${escapeHtml(phone)}</span></div>
    <div class="confirm-row"><span>Entrega</span><span>${deliveryMode === 'envio' ? 'Despacho' : 'Retiro'}</span></div>
    ${deliveryMode === 'envio' ? `<div class="confirm-row"><span>Dirección</span><span>${escapeHtml(address || 'No definida')}</span></div>` : ''}
    <div class="confirm-row"><span>Horario sugerido</span><span>${escapeHtml(getRequestedTime() || 'No indicada')}</span></div>
    ${notes ? `<div class="confirm-row"><span>Notas</span><span>${escapeHtml(notes)}</span></div>` : ''}
    <p class="confirm-section-title">Productos</p>
    ${itemsHtml}
    <p class="confirm-section-title">Pago</p>
    <div class="confirm-row"><span>Forma de pago</span><span>${escapeHtml(paymentLine)}</span></div>
    <div class="confirm-row"><span>Subtotal</span><span>${formatPrice(subtotal)}</span></div>
    ${deliveryMode === 'envio' ? `<div class="confirm-row"><span>Envío</span><span>${formatPrice(shipping)}</span></div>` : ''}
    ${computeBundleDiscount() ? `<div class="confirm-row"><span>2x1/3x2 aplicado</span><span>-${formatPrice(computeBundleDiscount())}</span></div>` : ''}
    ${STATE.appliedCoupon ? `<div class="confirm-row"><span>Descuento (${escapeHtml(STATE.appliedCoupon.code)})</span><span>-${formatPrice(STATE.appliedCoupon.discountAmount)}</span></div>` : ''}
    ${giftIsReached(total) ? `<div class="confirm-row"><span>🎁 Regalo</span><span>${escapeHtml(GIFT_PRODUCT_NAME)}</span></div>` : ''}
    <div class="confirm-row confirm-total"><span>Total</span><span>${formatPrice(total)}</span></div>
  `
}

function openConfirmModal() {
  elements.confirmSummary.innerHTML = buildConfirmSummaryHtml()
  elements.confirmError.style.display = 'none'
  elements.confirmModalSend.disabled = false
  elements.confirmModalSend.textContent = 'Confirmar y enviar por WhatsApp'
  elements.confirmModal.classList.add('open')
  elements.confirmModalBackdrop.classList.add('open')
  document.body.classList.add('modal-open')
}

function closeConfirmModal() {
  elements.confirmModal.classList.remove('open')
  elements.confirmModalBackdrop.classList.remove('open')
  document.body.classList.remove('modal-open')
}

function resetCartAfterOrder() {
  // The order is already saved server-side at this point - the cart MUST be cleared
  // no matter what happens next (WhatsApp opening, etc), or a second "Enviar" tap
  // creates a duplicate Order the encargado has to notice and cancel by hand.
  STATE.cart = []
  // Null it out before saveCart() so its own clearAppliedCoupon() call becomes a
  // no-op (it early-returns when there's nothing applied) instead of overwriting the
  // UI with a "tu carrito cambió, vuelve a aplicar el cupón" message that makes no
  // sense right after a successful order.
  STATE.appliedCoupon = null
  if (elements.couponCode) elements.couponCode.value = ''
  if (elements.couponMessage) {
    elements.couponMessage.textContent = ''
    elements.couponMessage.className = 'coupon-message'
  }
  saveCart()  // persists the emptied cart to localStorage too - not just STATE.cart
  renderCart()  // repaints cart items + upsell suggestions + every summary hint
}

async function handleConfirmSend() {
  elements.confirmModalSend.disabled = true
  elements.confirmModalSend.textContent = 'Enviando...'
  elements.confirmError.style.display = 'none'

  saveCustomer()
  const result = await saveOrder()
  if (!result.ok) {
    // Order was never saved - the customer keeps their cart to retry, nothing to clear.
    elements.confirmError.textContent = result.message
    elements.confirmError.style.display = 'block'
    elements.confirmModalSend.disabled = false
    elements.confirmModalSend.textContent = 'Confirmar y enviar por WhatsApp'
    return
  }

  try {
    const response = await fetch('/api/whatsapp-number')
    const data = await response.json()
    const whatsappNumber = data.whatsappNumber || '56900000000'
    window.open(`https://wa.me/${whatsappNumber}?text=${buildWhatsAppText()}`, '_blank')
  } catch (error) {
    window.open(`https://wa.me/56900000000?text=${buildWhatsAppText()}`, '_blank')
  }
  resetCartAfterOrder()
  closeConfirmModal()
}

async function saveOrder() {
  const deliveryMode = getDeliveryMode()

  try {
    const response = await fetch('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: STATE.cart.map((item) => ({
          id: item.id,
          quantity: item.quantity,
          options: (item.selectedOptions || []).map((o) => o.id),
        })),
        customerName: elements.name.value.trim() || 'Cliente',
        phone: elements.phone.value.trim(),
        address: elements.address.value.trim(),
        deliveryMode,
        paymentMethod: getPaymentMethod(),
        cashAmount: getPaymentMethod() === 'efectivo' ? Number(elements.cashAmount.value) || null : null,
        notes: elements.notes.value.trim(),
        requestedTime: getRequestedTime(),
        lat: STATE.selectedLocation ? STATE.selectedLocation.lat : null,
        lng: STATE.selectedLocation ? STATE.selectedLocation.lng : null,
        couponCode: STATE.appliedCoupon ? STATE.appliedCoupon.code : null,
      }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok || data.ok === false) {
      return { ok: false, message: data.message || 'No se pudo guardar el pedido.' }
    }
    return { ok: true }
  } catch (error) {
    return { ok: false, message: 'No se pudo conectar con el servidor. Revisa tu conexión e intenta de nuevo.' }
  }
}

function getMissingFields() {
  const missing = []
  if (!elements.name.value.trim()) missing.push('tu nombre')
  if (!elements.phone.value.trim()) missing.push('tu teléfono')
  if (getDeliveryMode() === 'envio') {
    if (!STATE.selectedLocation) missing.push('confirma tu ubicación en el mapa')
    else if (!STATE.deliveryCovered) missing.push('una dirección dentro de la zona de reparto')
    const subtotal = STATE.cart.reduce((sum, item) => sum + item.price * item.quantity, 0)
    if (getMinOrderShortfall(subtotal) > 0) {
      missing.push(`el pedido mínimo para despacho (${formatPrice(MIN_DELIVERY_ORDER)})`)
    }
  }
  if (!elements.requestedTime.value) {
    missing.push('el horario sugerido')
  } else if (!isWithinBusinessHours(elements.requestedTime.value)) {
    missing.push(`un horario sugerido entre las ${OPENS_AT} y las ${CLOSES_AT}`)
  }
  return missing
}

async function handleCheckout() {
  // Defense in depth - the button is already disabled while blocked, but this also
  // covers a stale disabled state if the hour ticked over without a re-render.
  if (isOutsideHoursNow() && !ACCEPT_ORDERS_OUTSIDE_HOURS) {
    alert(`Nuestro horario es de ${OPENS_AT} a ${CLOSES_AT}. Escríbenos por WhatsApp para coordinar.`)
    return
  }
  if (!STATE.cart.length) {
    alert('Agrega al menos un producto al carrito antes de enviar.');
    return
  }
  const missing = getMissingFields()
  if (missing.length) {
    alert(`Antes de enviar, completa: ${missing.join(', ')}.`)
    return
  }
  openConfirmModal()
}

window.addEventListener('load', () => {
  loadSavedCustomer()
  loadProducts()
  startMap()
  renderCart()
  updateHoursGateHint()
  // A customer can leave this tab open across the opening/closing boundary - re-check
  // every minute so the gate (and its message) stay correct without a reload.
  setInterval(updateHoursGateHint, 60000)

  document.querySelectorAll('input[name="delivery-mode"]').forEach((input) => {
    input.addEventListener('change', () => {
      toggleDeliveryFields()
      clearAppliedCoupon()
      updateSummary()
    })
  })

  elements.couponApplyBtn.addEventListener('click', applyCoupon)

  document.querySelectorAll('input[name="payment-method"]').forEach((input) => {
    input.addEventListener('change', togglePaymentFields)
  })
  elements.cashAmount.addEventListener('input', updateChangeHint)
  toggleDeliveryFields()
  togglePaymentFields()

  elements.cartFab.addEventListener('click', openCart)
  elements.cartClose.addEventListener('click', closeCart)
  elements.cartBackdrop.addEventListener('click', closeCart)
  initCartSwipeToClose()
  if (elements.featuredBannerTrack) initFeaturedBannerSwipe()

  if (elements.featuredBannerDots) {
    elements.featuredBannerDots.addEventListener('click', (event) => {
      const dot = event.target.closest('[data-slide]')
      if (!dot) return
      goToFeaturedSlide(Number(dot.getAttribute('data-slide')))
      startFeaturedBannerAutoplay()
    })
  }

  elements.navToggle.addEventListener('click', openNav)
  elements.navClose.addEventListener('click', closeNav)
  elements.navBackdrop.addEventListener('click', closeNav)

  elements.productModalClose.addEventListener('click', closeProductModal)
  elements.productModalBackdrop.addEventListener('click', closeProductModal)
  elements.productModalAdd.addEventListener('click', handleModalAddClick)
  elements.productModalOptions.addEventListener('change', updateModalPrice)

  elements.confirmModalClose.addEventListener('click', closeConfirmModal)
  elements.confirmModalBackdrop.addEventListener('click', closeConfirmModal)
  elements.confirmModalEdit.addEventListener('click', closeConfirmModal)
  elements.confirmModalSend.addEventListener('click', handleConfirmSend)

  document.body.addEventListener('click', (event) => {
    const navLink = event.target.closest('[data-target]')
    if (navLink) {
      const target = document.getElementById(navLink.getAttribute('data-target'))
      closeNav()
      if (target) setTimeout(() => target.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
    }
    const details = event.target.closest('[data-details]')
    if (details) openProductModal(details.getAttribute('data-details'))
    const couponSlide = event.target.closest('[data-coupon-code]')
    if (couponSlide) {
      elements.couponCode.value = couponSlide.getAttribute('data-coupon-code')
      openCart()
      if (elements.phone.value.trim()) applyCoupon()
      else elements.couponCode.focus()
    }
    const add = event.target.closest('[data-add]')
    const remove = event.target.closest('[data-remove]')
    const increment = event.target.closest('[data-increment]')
    const decrement = event.target.closest('[data-decrement]')
    if (add) {
      addToCart(add.getAttribute('data-add'))
      openCart()
      closeProductModal()
    }
    if (remove) removeFromCart(remove.getAttribute('data-remove'))
    if (increment) incrementCartItem(increment.getAttribute('data-increment'))
    if (decrement) decrementCartItem(decrement.getAttribute('data-decrement'))
    const quickCash = event.target.closest('.quick-cash-option')
    if (quickCash) {
      elements.cashAmount.value = quickCash.dataset.amount
      updateChangeHint()
    }
    const suggestion = event.target.closest('.suggestion-item')
    if (suggestion) {
      const lat = Number(suggestion.dataset.lat)
      const lon = Number(suggestion.dataset.lon)
      const display = suggestion.dataset.display
      const precise = suggestion.dataset.precise === 'true'
      const typedText = elements.address.value.trim()
      const typedNumber = extractHouseNumber(typedText)
      // Trust OSM's own name only when it actually carries the house number the
      // customer typed - if OSM's "precise" flag is wrong, or the number just
      // isn't in the returned name, keep what the customer wrote so the delivery
      // number is never silently lost.
      const numberMissing = typedNumber && !display.includes(typedNumber)
      const isPrecise = precise && !numberMissing
      const label = isPrecise ? display : (typedText || display)
      elements.address.value = label
      setLocation(lat, lon, label, isPrecise)
      document.querySelector('.suggestions-list').innerHTML = ''
    }
  })

  let timeoutId = null
  elements.address.addEventListener('input', () => {
    clearTimeout(timeoutId)
    timeoutId = setTimeout(async () => {
      const results = await searchAddress(elements.address.value)
      if (!document.querySelector('.suggestions-list')) {
        const list = document.createElement('ul')
        list.className = 'suggestions-list'
        elements.address.parentNode.insertBefore(list, elements.address.nextSibling)
      }
      renderSuggestions(results)
    }, 300)
  })

  elements.checkoutBtn.addEventListener('click', handleCheckout)

  elements.productSearch.addEventListener('input', () => {
    renderProductGrid(elements.productSearch.value)
  })
})
