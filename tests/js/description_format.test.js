// node --test tests/js
const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')

const { normalize, blocks, toHtml } = require(path.join(__dirname, '../../app/static/js/description_format.js'))

const escapeHtml = (value) => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;')

const CHEF = '70 piezas elegidas por el chef:\r\n10 piezas California\r\n10 piezas Hosomaki salmón\r\n' +
  '10 piezas Ebi tempura\r\n10 piezas Avocado\r\n10 piezas Furai\r\n10 piezas Sake\r\n10 piezas Kanikama'

test('line breaks survive - one item per line, \\r\\n included', () => {
  assert.deepEqual(blocks(CHEF), [{ type: 'text', text: CHEF.replace(/\r\n/g, '\n') }])
  assert.equal(blocks(CHEF)[0].text.split('\n').length, 8)
})

test('each line is trimmed and 2+ empty lines collapse to one', () => {
  assert.equal(normalize('  uno  \n\n\n\n  dos\t\n\ntres  '), 'uno\n\ndos\n\ntres')
  assert.equal(normalize('\n\n  solo  \n\n'), 'solo')
})

test('lines starting with "- ", "* " or "•" become a list; other lines stay text', () => {
  assert.deepEqual(blocks('Incluye:\n- 10 California\n* 10 Avocado\n•10 Sake\nPara 4 personas'), [
    { type: 'text', text: 'Incluye:' },
    { type: 'list', items: ['10 California', '10 Avocado', '10 Sake'] },
    { type: 'text', text: 'Para 4 personas' },
  ])
  // a dash glued to a number is not a bullet
  assert.deepEqual(blocks('-10% en tu pedido\notra línea'), [{ type: 'text', text: '-10% en tu pedido\notra línea' }])
})

test('the older single-line "·" style is still a list', () => {
  assert.deepEqual(blocks('Pollo · Camarón · Salmón'), [{ type: 'list', items: ['Pollo', 'Camarón', 'Salmón'] }])
  assert.deepEqual(blocks('Solo una cosa'), [{ type: 'text', text: 'Solo una cosa' }])
  assert.deepEqual(blocks('   '), [])
})

test('HTML typed by the owner is escaped, never rendered', () => {
  const html = toHtml('<b>Rico</b>\n- <img src=x onerror=alert(1)>\n"comillas" & más', escapeHtml)
  assert.equal(html,
    '<p class="description-text">&lt;b&gt;Rico&lt;/b&gt;</p>' +
    '<ul class="description-list"><li>&lt;img src=x onerror=alert(1)&gt;</li></ul>' +
    '<p class="description-text">&quot;comillas&quot; &amp; más</p>')
  assert.ok(!html.includes('<br'))
})
