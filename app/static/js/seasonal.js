// Seasonal decorations on the menu ("Adornos de temporada"). The server already decided
// which celebration shows today and how it looks (app/seasons.py, #season-data); this
// only plays it: a few particles over the header and carousel that stop on their own,
// one crossing per visit, and a small burst of emojis when something is added to the
// cart. Never over the cart, never catching taps (pointer-events: none), no audio, and
// with prefers-reduced-motion only the colors stay. Paused while the tab is hidden.
// The menu loads it only when a celebration is on; tests/js require()s the pure parts.
;(function (root) {
  'use strict'

  const AMBIENT_MS = 10000 // particles stop being added after this much visible time
  const SPAWN_EVERY_MS = 650
  const MAX_PARTICLES = 12
  const BURST_MS = 800
  const BURST_COUNT = 5
  const CROSSING_MS = 6500
  const CROSSED_KEY = 'menu-season-crossed'
  const CLICK_TO_ADD_MS = 1000 // a tap and its "added" event belong together within this

  // What to play: with reduced motion, nothing moves (the accent colors are CSS).
  function plan (season, reducedMotion) {
    const moving = !reducedMotion
    return {
      ambient: moving && Boolean(season.ambient),
      crossing: moving && Boolean(season.ambient) && Boolean(season.crossing),
      burst: moving && Boolean(season.burstOn),
    }
  }

  // A burst only when none is playing: tapping "+" five times fast gives one burst,
  // not five piled up.
  function createBurstGate (windowMs = BURST_MS) {
    let last = -Infinity
    return function allow (now) {
      if (now - last < windowMs) return false
      last = now
      return true
    }
  }

  // Where each emoji of a burst flies: up and fanned out, a little apart in time.
  function burstVectors (count, emojis, random = Math.random) {
    return Array.from({ length: count }, (_, i) => {
      const spread = count > 1 ? i / (count - 1) - 0.5 : 0
      return {
        emoji: emojis[i % emojis.length],
        dx: Math.round(spread * 90 + (random() - 0.5) * 16),
        dy: -Math.round(60 + random() * 40),
        delay: Math.round(random() * 90),
      }
    })
  }

  // One crossing per visit (this tab); the owner's preview always shows it.
  function shouldCross (storage, preview) {
    if (preview) return true
    try { return storage.getItem(CROSSED_KEY) !== '1' } catch { return true }
  }

  function markCrossed (storage) {
    try { storage.setItem(CROSSED_KEY, '1') } catch {}
  }

  // Visible time spent so far, counting only while the tab is showing.
  function createVisibleClock (now) {
    let spent = 0
    let since = now
    return {
      pause (at) { if (since !== null) { spent += at - since; since = null } },
      resume (at) { if (since === null) since = at },
      elapsed (at) { return spent + (since === null ? 0 : at - since) },
    }
  }

  const api = { AMBIENT_MS, MAX_PARTICLES, BURST_MS, BURST_COUNT, plan, createBurstGate, burstVectors, shouldCross, markCrossed, createVisibleClock }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api
    return
  }
  root.Seasonal = api

  // --- In the page ---------------------------------------------------------------------
  const dataTag = document.getElementById('season-data')
  if (!dataTag) return
  let season
  try { season = JSON.parse(dataTag.textContent) } catch { return }
  const reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const play = plan(season, reducedMotion)
  const random = (min, max) => min + Math.random() * (max - min)

  // The band over the header and the carousel: where particles and the crossing live.
  function decoratedArea () {
    const header = document.querySelector('.page-shell > .hero')
    const carousel = document.getElementById('hero-carousel')
    if (!header) return null
    const top = header.getBoundingClientRect().top + window.scrollY
    const bottom = (carousel || header).getBoundingClientRect().bottom + window.scrollY
    return { top, height: Math.max(0, bottom - top), header, carousel }
  }

  function startAmbient () {
    const area = decoratedArea()
    if (!area || !area.height) return
    const layer = document.createElement('div')
    layer.className = 'season-layer'
    layer.setAttribute('aria-hidden', 'true')
    const place = () => {
      const now = decoratedArea()
      if (!now) return
      layer.style.top = `${now.top}px`
      layer.style.height = `${now.height}px`
    }
    place()
    document.body.appendChild(layer)
    window.addEventListener('resize', place, { passive: true })

    const clock = createVisibleClock(performance.now())
    let timer = null
    let stopped = false
    let live = 0

    function spawn () {
      if (stopped || live >= MAX_PARTICLES) return
      const flake = document.createElement('span')
      flake.className = 'season-particle'
      flake.textContent = season.particles[Math.floor(Math.random() * season.particles.length)]
      flake.style.left = `${random(2, 96)}%`
      flake.style.fontSize = `${Math.round(random(13, 20))}px`
      flake.style.setProperty('--fall', `${layer.offsetHeight + 30}px`)
      flake.style.setProperty('--sway', `${Math.round(random(-28, 28))}px`)
      flake.style.setProperty('--alpha', random(0.55, 0.85).toFixed(2))
      flake.style.animationDuration = `${Math.round(random(5200, 7400))}ms`
      flake.addEventListener('animationend', () => { flake.remove(); live -= 1; if (stopped && !live) layer.remove() })
      live += 1
      layer.appendChild(flake)
    }

    function tick () {
      if (clock.elapsed(performance.now()) >= AMBIENT_MS) return stop()
      spawn()
    }

    function stop () {
      if (stopped) return
      stopped = true
      clearInterval(timer)
      window.removeEventListener('resize', place)
      if (!live) layer.remove()
    }

    function resume () {
      if (stopped) return
      clearInterval(timer)
      timer = setInterval(tick, SPAWN_EVERY_MS)
    }

    // Scrolled past the carousel: no new particles; those falling finish and go.
    const watched = area.carousel || area.header
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => !entry.isIntersecting)) { stop(); observer.disconnect() }
      })
      observer.observe(watched)
    }

    document.addEventListener('visibilitychange', () => {
      const now = performance.now()
      if (document.hidden) {
        clock.pause(now)
        clearInterval(timer)
        layer.classList.add('is-paused')
      } else {
        clock.resume(now)
        layer.classList.remove('is-paused')
        resume()
      }
    })

    spawn()
    resume()
    return layer
  }

  function startCrossing (layer) {
    if (!layer || !shouldCross(sessionStorage, season.preview)) return
    markCrossed(sessionStorage)
    const rider = document.createElement('span')
    rider.className = 'season-crossing'
    rider.textContent = season.crossing
    rider.style.setProperty('--from', `${document.documentElement.clientWidth}px`)
    rider.style.animationDuration = `${CROSSING_MS}ms`
    rider.addEventListener('animationend', () => rider.remove())
    // A moment after the page settles, so it isn't missed while the first slide loads.
    setTimeout(() => { if (layer.isConnected) layer.appendChild(rider) }, 1200)
  }

  // Where a burst starts. On a phone, adding opens the cart as a sheet over the menu:
  // the burst waits for it to finish opening and rises from its top edge, over the
  // dimmed menu - never inside the cart. On a desktop (the cart is a column beside the
  // menu) it rises from the tapped button, as does one from the product modal there.
  const SHEET_OPEN_WAIT_MS = 400

  function cartSheet () {
    const panel = document.getElementById('cart-panel')
    if (!panel || !panel.classList.contains('open')) return null
    return getComputedStyle(panel).position === 'fixed' ? panel : null
  }

  function afterSheetOpens (sheet, then) {
    let done = false
    const finish = () => { if (!done) { done = true; sheet.removeEventListener('transitionend', onEnd); then() } }
    const onEnd = (event) => { if (event.target === sheet) finish() }
    sheet.addEventListener('transitionend', onEnd)
    setTimeout(finish, SHEET_OPEN_WAIT_MS)
  }

  function launchBurst (x, y) {
    const layer = document.createElement('div')
    layer.className = 'season-burst'
    layer.setAttribute('aria-hidden', 'true')
    layer.style.left = `${x}px`
    layer.style.top = `${y}px`
    for (const piece of burstVectors(BURST_COUNT, season.burst)) {
      const span = document.createElement('span')
      span.textContent = piece.emoji
      span.style.setProperty('--dx', `${piece.dx}px`)
      span.style.setProperty('--dy', `${piece.dy}px`)
      span.style.animationDelay = `${piece.delay}ms`
      layer.appendChild(span)
    }
    document.body.appendChild(layer)
    setTimeout(() => layer.remove(), BURST_MS + 150)
  }

  function startBursts () {
    const allow = createBurstGate(BURST_MS)
    let lastTap = null
    // Remember the "+" or "Agregar" tapped on the menu (never one inside the cart); the
    // menu says when the product actually went in (menu:cart-add, menu.js addToCart).
    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-add], #product-modal-add')
      lastTap = button && !button.closest('#cart-panel')
        ? { rect: button.getBoundingClientRect(), at: performance.now() }
        : null
    }, true)
    document.addEventListener('menu:cart-add', () => {
      const now = performance.now()
      if (!lastTap || now - lastTap.at > CLICK_TO_ADD_MS || document.hidden || !allow(now)) return
      const { rect } = lastTap
      lastTap = null
      const x = rect.left + rect.width / 2
      // menu:cart-add fires inside addToCart, just before the menu opens the cart.
      setTimeout(() => {
        const sheet = cartSheet()
        if (!sheet) return launchBurst(x, rect.top + rect.height / 2)
        afterSheetOpens(sheet, () => {
          const edge = sheet.getBoundingClientRect().top
          const margin = 28
          launchBurst(Math.min(Math.max(x, margin), window.innerWidth - margin), edge - 6)
        })
      }, 0)
    })
  }

  function start () {
    if (play.ambient) {
      const layer = startAmbient()
      if (play.crossing) startCrossing(layer)
    }
    if (play.burst) startBursts()
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start)
  else start()
})(this)
