// The few Markdown marks the model puts in its replies, read into parts the page draws as bold, italic and code (found on 2026-10-21: the chat showed **Winter Vacation** with its stars).
// Pure and tiny on purpose: it knows only **bold**, *italic* and `code`, and it returns PARTS, never HTML, so nothing a reply says can become markup: the page draws each part as text inside its own element.
// Anything it does not recognise, an unmatched star, a bullet "* item", an underscore, a "<b>", is left exactly as written. Tested under Node (tests/test_markdown_lite.py).

const MARKS = /\*\*([^*\n]+?)\*\*|`([^`\n]+)`|\*([^*\s][^*\n]*?)\*/g

export function inlineParts(text) {
  if (typeof text !== 'string' || text === '') return []
  const parts = []
  let last = 0
  for (const match of text.matchAll(MARKS)) {
    if (match.index > last) parts.push({ kind: 'text', text: text.slice(last, match.index) })
    if (match[1] !== undefined) parts.push({ kind: 'bold', text: match[1] })
    else if (match[2] !== undefined) parts.push({ kind: 'code', text: match[2] })
    else parts.push({ kind: 'italic', text: match[3] })
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push({ kind: 'text', text: text.slice(last) })
  return parts
}
