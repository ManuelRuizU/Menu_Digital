// Helper for tests/test_whatsapp_message.py (not a test file itself - node --test skips it):
// reads [{order, customer}] from the JSON file given as argument and prints the WhatsApp
// texts the menu would send, as a JSON array - so Python can compare them to total_price.
const fs = require('node:fs')
const path = require('node:path')

const { buildWhatsAppLines } = require(path.join(__dirname, '../../app/static/js/order_message.js'))

const scenarios = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
process.stdout.write(JSON.stringify(scenarios.map(({ order, customer }) => buildWhatsAppLines(order, customer).join('\n'))))
