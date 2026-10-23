// The big carousel at the top of the menu. The server renders every slide (the first
// one with fetchpriority="high"); this only moves the track: autoplay every 5 s, paused
// on hover, touch and keyboard focus, swipe, dots and arrows. No autoplay with one slide
// or when the system asks for reduced motion. The menu loads it as window.HeroCarousel;
// tests/js require()s the pure helpers.
;(function (root) {
  'use strict'

  const AUTOPLAY_MS = 5000
  const SWIPE_THRESHOLD = 0.18 // share of the width a swipe must travel to change slide

  // index after moving by step, wrapping around both ends.
  function wrapIndex (index, step, count) {
    return ((index + step) % count + count) % count
  }

  function shouldAutoplay (count, reducedMotion) {
    return count > 1 && !reducedMotion
  }

  function mount (el, win) {
    const track = el.querySelector('.hero-track')
    const slides = Array.from(el.querySelectorAll('.hero-slide'))
    const dots = Array.from(el.querySelectorAll('.hero-dot'))
    const count = slides.length
    if (!track || count < 2) return null

    const motionQuery = win.matchMedia ? win.matchMedia('(prefers-reduced-motion: reduce)') : null
    let index = 0
    let timer = null
    const pausedBy = new Set() // hover / touch / focus / hidden - autoplay waits until none

    function show (next) {
      index = wrapIndex(next, 0, count)
      track.style.transform = `translateX(-${index * 100}%)`
      slides.forEach((slide, i) => {
        const current = i === index
        slide.setAttribute('aria-hidden', current ? 'false' : 'true')
        // Off-screen slides keep their buttons out of the tab order.
        if ('inert' in slide) slide.inert = !current
      })
      dots.forEach((dot, i) => {
        dot.classList.toggle('active', i === index)
        dot.setAttribute('aria-current', i === index ? 'true' : 'false')
      })
    }

    function restart () {
      clearInterval(timer)
      timer = null
      const reduced = motionQuery ? motionQuery.matches : false
      if (shouldAutoplay(count, reduced) && pausedBy.size === 0) {
        timer = setInterval(() => show(index + 1), AUTOPLAY_MS)
      }
    }

    function pause (reason) { pausedBy.add(reason); restart() }
    function resume (reason) { pausedBy.delete(reason); restart() }

    el.addEventListener('click', (event) => {
      const dot = event.target.closest('.hero-dot')
      const arrow = event.target.closest('.hero-arrow')
      if (dot) show(Number(dot.dataset.slide))
      else if (arrow) show(index + Number(arrow.dataset.step))
      else return
      restart()
    })
    el.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      show(index + (event.key === 'ArrowRight' ? 1 : -1))
    })
    el.addEventListener('mouseenter', () => pause('hover'))
    el.addEventListener('mouseleave', () => resume('hover'))
    el.addEventListener('focusin', () => pause('focus'))
    el.addEventListener('focusout', (event) => {
      if (!el.contains(event.relatedTarget)) resume('focus')
    })
    win.document.addEventListener('visibilitychange', () => {
      if (win.document.hidden) pause('hidden')
      else resume('hidden')
    })
    if (motionQuery && motionQuery.addEventListener) motionQuery.addEventListener('change', restart)

    // Swipe: the track follows the finger, then snaps to the nearest slide.
    let startX = 0
    let startY = 0
    let deltaX = 0
    let dragging = false
    let horizontal = null
    let swiped = false
    // A swipe that ends over a coupon slide (a button) must not also "tap" it.
    el.addEventListener('click', (event) => {
      if (!swiped) return
      swiped = false
      event.preventDefault()
      event.stopPropagation()
    }, true)
    track.addEventListener('touchstart', (event) => {
      startX = event.touches[0].clientX
      startY = event.touches[0].clientY
      deltaX = 0
      dragging = true
      horizontal = null
      swiped = false
      pause('touch')
    }, { passive: true })
    track.addEventListener('touchmove', (event) => {
      if (!dragging) return
      const dx = event.touches[0].clientX - startX
      const dy = event.touches[0].clientY - startY
      if (horizontal === null && (Math.abs(dx) > 6 || Math.abs(dy) > 6)) horizontal = Math.abs(dx) > Math.abs(dy)
      if (!horizontal) return // a vertical drag is the page scrolling - leave it alone
      deltaX = dx
      track.classList.add('dragging')
      const percent = (deltaX / (el.offsetWidth || 1)) * 100
      track.style.transform = `translateX(calc(-${index * 100}% + ${percent}%))`
    }, { passive: true })
    function endTouch () {
      if (!dragging) return
      dragging = false
      track.classList.remove('dragging')
      const share = deltaX / (el.offsetWidth || 1)
      swiped = horizontal && Math.abs(deltaX) > 10
      if (horizontal && share <= -SWIPE_THRESHOLD) show(index + 1)
      else if (horizontal && share >= SWIPE_THRESHOLD) show(index - 1)
      else show(index)
      resume('touch')
    }
    track.addEventListener('touchend', endTouch)
    track.addEventListener('touchcancel', endTouch)

    show(0)
    restart()
    return { show, get index () { return index } }
  }

  const api = { wrapIndex, shouldAutoplay, mount }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api
  } else {
    root.HeroCarousel = api
    const el = root.document && root.document.getElementById('hero-carousel')
    if (el) mount(el, root)
  }
})(this)
