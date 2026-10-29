// Product and subcategory descriptions as the owner typed them: one item per line. Turns
// the raw text into blocks - plain text (shown with white-space: pre-line) and bullet
// lists (lines starting with "- ", "* " or "•") - and never into HTML: callers set
// textContent or escape every piece. The menu loads it as window.DescriptionFormat;
// tests/js require()s it.
;(function (root) {
  'use strict'

  const BULLET = /^(?:[-*]\s+|•\s*)(.+)$/

  // Each line trimmed, \r\n treated as \n, and 3+ line breaks in a row (2+ empty lines)
  // collapsed to a single empty line.
  function normalize (text) {
    return String(text || '')
      .replace(/\r\n?/g, '\n')
      .split('\n')
      .map((line) => line.trim())
      .join('\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim()
  }

  // [{ type: 'text', text }] and [{ type: 'list', items: [...] }], in order.
  function blocks (description) {
    const text = normalize(description)
    if (!text) return []
    // Older descriptions separate items with a typed "·" on a single line - still a list.
    if (!text.includes('\n')) {
      const segments = text.split('·').map((segment) => segment.trim()).filter(Boolean)
      return segments.length > 1 ? [{ type: 'list', items: segments }] : [{ type: 'text', text }]
    }
    const result = []
    for (const line of text.split('\n')) {
      const bullet = line.match(BULLET)
      const last = result[result.length - 1]
      if (bullet) {
        if (last && last.type === 'list') last.items.push(bullet[1])
        else result.push({ type: 'list', items: [bullet[1]] })
      } else if (last && last.type === 'text') {
        last.text += '\n' + line
      } else if (line) {
        result.push({ type: 'text', text: line })
      }
    }
    // A blank line right before or after a list is just spacing around it.
    return result.map((block) => (block.type === 'text' ? { type: 'text', text: block.text.trim() } : block))
      .filter((block) => block.type === 'list' || block.text)
  }

  // Safe HTML for a template string: every piece goes through the caller's escapeHtml.
  function toHtml (description, escapeHtml) {
    return blocks(description).map((block) => (block.type === 'list'
      ? `<ul class="description-list">${block.items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
      : `<p class="description-text">${escapeHtml(block.text)}</p>`)).join('')
  }

  // The same blocks as DOM nodes, built with textContent only.
  function render (container, description) {
    const doc = container.ownerDocument
    container.textContent = ''
    blocks(description).forEach((block) => {
      if (block.type === 'list') {
        const list = doc.createElement('ul')
        list.className = 'description-list'
        block.items.forEach((itemText) => {
          const item = doc.createElement('li')
          item.textContent = itemText
          list.appendChild(item)
        })
        container.appendChild(list)
      } else {
        const paragraph = doc.createElement('p')
        paragraph.className = 'description-text'
        paragraph.textContent = block.text
        container.appendChild(paragraph)
      }
    })
  }

  const api = { normalize, blocks, toHtml, render }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.DescriptionFormat = api
})(this)
