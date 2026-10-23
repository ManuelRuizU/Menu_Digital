// "Explora nuestro menú": two rows of category tiles that slide sideways (CSS does the
// layout, the swipe and the snapping). This only drives the ‹ › arrows on a wider
// screen: each one shows only while its side has more to see - and brings a tile reached
// with Tab fully into view (the browser leaves a half-peeking one where it is). The menu
// loads it as window.ExploreScroller; tests/js require()s arrowState.
;(function (root) {
  'use strict'

  // Which arrows to show for a scroll position (1px of slack for fractional pixels).
  function arrowState (scrollLeft, scrollWidth, clientWidth) {
    return { prev: scrollLeft > 1, next: scrollLeft + clientWidth < scrollWidth - 1 }
  }

  function mount (section, win) {
    const grid = section.querySelector('.explore-grid')
    const prev = section.querySelector('.explore-arrow-prev')
    const next = section.querySelector('.explore-arrow-next')
    if (!grid) return null
    const reducedMotion = () => !!(win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches)

    grid.addEventListener('focusin', (event) => {
      const tile = event.target.closest('.explore-tile')
      if (tile) tile.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth' })
    })
    if (!prev || !next) return null // 4 or fewer: a static 2×2, nothing to page through

    function update () {
      const state = arrowState(grid.scrollLeft, grid.scrollWidth, grid.clientWidth)
      prev.hidden = !state.prev
      next.hidden = !state.next
    }

    function scrollByPage (direction) {
      const tile = grid.querySelector('.explore-tile')
      const column = tile ? tile.getBoundingClientRect().width : grid.clientWidth / 2
      // Whole columns only - the snap points then line up exactly.
      const columns = Math.max(1, Math.floor(grid.clientWidth / column) - 1)
      grid.scrollBy({ left: direction * columns * column, behavior: reducedMotion() ? 'auto' : 'smooth' })
    }

    prev.addEventListener('click', () => scrollByPage(-1))
    next.addEventListener('click', () => scrollByPage(1))
    grid.addEventListener('scroll', update, { passive: true })
    if (win.ResizeObserver) new win.ResizeObserver(update).observe(grid)
    else win.addEventListener('resize', update)
    update()
    return { update }
  }

  const api = { arrowState, mount }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api
  } else {
    root.ExploreScroller = api
    const section = root.document && root.document.getElementById('explore')
    if (section) mount(section, root)
  }
})(this)
