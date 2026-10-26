// The few Markdown marks the model puts in its replies, read into parts the page draws as bold, italic and code (found on 2026-10-21: the chat showed **Winter Vacation** with its stars).
// Pure and tiny on purpose: it knows only **bold**, *italic* and `code`, and it returns PARTS, never HTML, so nothing a reply says can become markup: the page draws each part as text inside its own element.
// Anything it does not recognise, an unmatched star, a bullet "* item", an underscore, a "<b>", is left exactly as written. Tested under Node (tests/test_markdown_lite.py).

// An address in a reply is made a link only when it is one of Google's own (the result of something Diya added to your Google account, 2026-10-26): its host, read the way the browser reads it, is google.com or one
// of its subdomains. Anything else stays the words it was, and a "https://google.com@evil.example" or a "https://google.com.evil.example" is not Google's.
const MARKS = /\*\*([^*\n]+?)\*\*|`([^`\n]+)`|\*([^*\s][^*\n]*?)\*|(https:\/\/[^\s<>"'`*)]+)/g

function googleLink(address) {
  let url = address
  let tail = ''
  while (/[.,;:!?]$/.test(url)) {
    tail = url.slice(-1) + tail
    url = url.slice(0, -1)
  }
  try {
    const host = new URL(url).hostname
    if (host === 'google.com' || host.endsWith('.google.com')) return { url, tail }
  } catch {
    // not an address
  }
  return null
}

export function inlineParts(text) {
  if (typeof text !== 'string' || text === '') return []
  const parts = []
  let last = 0
  for (const match of text.matchAll(MARKS)) {
    if (match.index > last) parts.push({ kind: 'text', text: text.slice(last, match.index) })
    if (match[1] !== undefined) parts.push({ kind: 'bold', text: match[1] })
    else if (match[2] !== undefined) parts.push({ kind: 'code', text: match[2] })
    else if (match[3] !== undefined) parts.push({ kind: 'italic', text: match[3] })
    else {
      const link = googleLink(match[4])
      if (link) {
        parts.push({ kind: 'link', text: link.url })
        if (link.tail) parts.push({ kind: 'text', text: link.tail })
      } else {
        parts.push({ kind: 'text', text: match[4] })
      }
    }
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push({ kind: 'text', text: text.slice(last) })
  return parts
}
