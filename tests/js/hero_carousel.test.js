// node --test tests/js
const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')

const { wrapIndex, shouldAutoplay } = require(path.join(__dirname, '../../app/static/js/hero_carousel.js'))

test('arrows and autoplay wrap around both ends', () => {
  assert.equal(wrapIndex(0, 1, 3), 1)
  assert.equal(wrapIndex(2, 1, 3), 0)
  assert.equal(wrapIndex(0, -1, 3), 2)
  assert.equal(wrapIndex(4, 0, 3), 1)
})

test('autoplay only with two or more slides and without reduced motion', () => {
  assert.equal(shouldAutoplay(1, false), false)
  assert.equal(shouldAutoplay(2, false), true)
  assert.equal(shouldAutoplay(5, true), false)
})
