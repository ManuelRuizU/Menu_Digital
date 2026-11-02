const test = require('node:test')
const assert = require('node:assert/strict')
const Seasonal = require('../../app/static/js/seasonal.js')

const season = { ambient: true, burstOn: true, crossing: '🦌🦌🛷🎅' }

test('plan: reduced motion keeps only the colors (nothing moves)', () => {
  assert.deepEqual(Seasonal.plan(season, true), { ambient: false, crossing: false, burst: false })
  assert.deepEqual(Seasonal.plan(season, false), { ambient: true, crossing: true, burst: true })
})

test('plan: follows the effects the owner chose', () => {
  assert.deepEqual(Seasonal.plan({ ...season, ambient: false }, false), { ambient: false, crossing: false, burst: true })
  assert.deepEqual(Seasonal.plan({ ...season, burstOn: false }, false), { ambient: true, crossing: true, burst: false })
  assert.equal(Seasonal.plan({ ...season, crossing: '' }, false).crossing, false)
})

test('burst gate: tapping fast gives one burst, never a pile', () => {
  const allow = Seasonal.createBurstGate(800)
  assert.equal(allow(1000), true)
  assert.equal(allow(1100), false)
  assert.equal(allow(1700), false)
  assert.equal(allow(1800), true)
})

test('burst: 4 to 6 emojis of the theme, flying up', () => {
  assert.ok(Seasonal.BURST_COUNT >= 4 && Seasonal.BURST_COUNT <= 6)
  assert.ok(Seasonal.BURST_MS < 1000)
  const pieces = Seasonal.burstVectors(5, ['🎄', '🎁', '⭐'], () => 0.5)
  assert.deepEqual(pieces.map((p) => p.emoji), ['🎄', '🎁', '⭐', '🎄', '🎁'])
  assert.ok(pieces.every((p) => p.dy < 0))
  assert.ok(pieces[0].dx < 0 && pieces[4].dx > 0)
})

test('crossing: once per visit, always in the owner preview', () => {
  const data = {}
  const storage = { getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v } }
  assert.equal(Seasonal.shouldCross(storage, false), true)
  Seasonal.markCrossed(storage)
  assert.equal(Seasonal.shouldCross(storage, false), false)
  assert.equal(Seasonal.shouldCross(storage, true), true)
  const broken = { getItem () { throw new Error('blocked') }, setItem () { throw new Error('blocked') } }
  assert.equal(Seasonal.shouldCross(broken, false), true)
  assert.doesNotThrow(() => Seasonal.markCrossed(broken))
})

test('visible clock: hidden tab time does not count toward the ~10 s', () => {
  const clock = Seasonal.createVisibleClock(0)
  assert.equal(clock.elapsed(4000), 4000)
  clock.pause(4000)
  assert.equal(clock.elapsed(60000), 4000)
  clock.resume(60000)
  assert.equal(clock.elapsed(66000), 10000)
  assert.equal(Seasonal.AMBIENT_MS, 10000)
  assert.ok(Seasonal.MAX_PARTICLES <= 14)
})
