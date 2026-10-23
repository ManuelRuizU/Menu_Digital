// node --test tests/js
const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')

const { arrowState } = require(path.join(__dirname, '../../app/static/js/explore_scroller.js'))

test('everything fits: no arrows', () => {
  assert.deepEqual(arrowState(0, 1120, 1120), { prev: false, next: false })
})

test('at the start only "next", at the end only "prev", in between both', () => {
  assert.deepEqual(arrowState(0, 1800, 1120), { prev: false, next: true })
  assert.deepEqual(arrowState(680, 1800, 1120), { prev: true, next: false })
  assert.deepEqual(arrowState(300, 1800, 1120), { prev: true, next: true })
})

test('a fractional pixel short of the end counts as the end', () => {
  assert.deepEqual(arrowState(679.5, 1800, 1120), { prev: true, next: false })
})
